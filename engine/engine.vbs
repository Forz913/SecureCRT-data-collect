' engine.vbs - SecureCRT 批量取数引擎（每进程一台服务器）
' 用法: SecureCRT.exe /SCRIPT engine.vbs /ARG <任务文件绝对路径>
' 任务文件: UTF-8，每行一个字段，共 9 行:
'   IP / 主机名 / 账号 / 密码 / 超时秒数 / 查询指令 / 结果文件前缀(绝对路径) / 停止标志文件(绝对路径) / run_id
' 输出: <前缀>_raw.txt（原始屏幕输出）、<前缀>_status.txt（IP<TAB>状态<TAB>原因<TAB>run_id）
' 状态: SUCCESS / FAIL / STOPPED
' 注意: 不使用 crt.Quit —— SecureCRT 单实例，Quit 会关掉用户自己的窗口
' 提示符识别: 候选 <主机名>（用户视图）/ [主机名]（系统视图）/ 裸提示符 主机名>（实测形态），分页标记 ---- More ---- 兜底
'            按行坐标取屏拼接；不再依赖字面量提示符匹配（原"输出捕获异常/捕获不完整"判定已移除）
Option Explicit

Dim g_fso
Set g_fso = CreateObject("Scripting.FileSystemObject")

Function ReadFileUtf8(strPath)
    If Not g_fso.FileExists(strPath) Then
        ReadFileUtf8 = ""
        Exit Function
    End If
    Dim st
    Set st = CreateObject("ADODB.Stream")
    st.Type = 2
    st.Charset = "utf-8"
    st.Open
    st.LoadFromFile strPath
    ReadFileUtf8 = st.ReadText
    st.Close
End Function

Sub WriteFileUtf8(strPath, strContent)
    Dim st
    Set st = CreateObject("ADODB.Stream")
    st.Type = 2
    st.Charset = "utf-8"
    st.Open
    st.WriteText strContent
    st.SaveToFile strPath, 2
    st.Close
End Sub

Sub WriteStatus(strPrefix, strIp, strStatus, strReason, strRunId)
    WriteFileUtf8 strPrefix & "_status.txt", strIp & vbTab & strStatus & vbTab & strReason & vbTab & strRunId
End Sub

Sub DisconnectQuietly()
    On Error Resume Next
    crt.Session.Disconnect
    On Error GoTo 0
End Sub

Sub Main()
    Dim taskPath, content, lines
    Dim ip, hostname, user, passwd
    Dim timeoutSec, command, prefix, stopFlagPath, runId
    Dim n, rawOut, nStart, nEnd, nRow, dDeadline, bDone, chk

    If crt.Arguments.Count < 1 Then
        Exit Sub
    End If
    taskPath = crt.Arguments.GetArg(0)

    content = ReadFileUtf8(taskPath)
    If content = "" Then
        Exit Sub
    End If
    content = Replace(content, vbCrLf, vbLf)
    content = Replace(content, vbCr, vbLf)
    lines = Split(content, vbLf)
    If UBound(lines) < 8 Then
        Exit Sub
    End If

    ip = Trim(lines(0))
    hostname = Trim(lines(1))
    user = Trim(lines(2))
    passwd = lines(3)
    timeoutSec = CLng(Trim(lines(4)))
    command = Trim(lines(5))
    prefix = Trim(lines(6))
    stopFlagPath = Trim(lines(7))
    runId = Trim(lines(8))

    If g_fso.FileExists(stopFlagPath) Then
        WriteStatus prefix, ip, "STOPPED", "用户停止", runId
        Exit Sub
    End If

    ' 全程容错：脚本运行时错误降级为失败状态，由主程序状态轮询收敛
    On Error Resume Next
    crt.Session.Connect "/SSH2 /ACCEPTHOSTKEYS /L " & user & " /PASSWORD """ & passwd & """ " & ip
    If Err.Number <> 0 Then
        WriteStatus prefix, ip, "FAIL", "连接异常: " & Err.Description, runId
        DisconnectQuietly
        Exit Sub
    End If

    ' 提示符候选：<主机名>（用户视图）/ [主机名]（系统视图）/ 主机名>（裸提示符，实测形态）/ 分页标记
    Dim arrWait(3)
    arrWait(0) = "<" & hostname & ">"
    arrWait(1) = "[" & hostname & "]"
    arrWait(2) = hostname & ">"
    arrWait(3) = "---- More ----"

    n = crt.Screen.WaitForStrings(arrWait, 30, True)
    If n = 0 Then
        WriteStatus prefix, ip, "FAIL", "连接后30秒未出现命令提示符(连接失败/认证失败/不可达/清单主机名与实际提示符不符)", runId
        DisconnectQuietly
        Exit Sub
    End If

    crt.Screen.Send "screen-length 0 temporary" & vbCr
    n = crt.Screen.WaitForStrings(arrWait, 15, True)
    If n = 0 Then
        WriteStatus prefix, ip, "FAIL", "关闭分页后未回到命令提示符", runId
        DisconnectQuietly
        Exit Sub
    End If

    crt.Screen.Send command & vbCr
    ' 等待命令回显结束：匹配"指令+换行"（字面量，不含提示符），避免裸提示符形态命中回显行
    If Not crt.Screen.WaitForString(command & vbCr, 10) Then
        WriteStatus prefix, ip, "FAIL", "未检测到命令回显", runId
        DisconnectQuietly
        Exit Sub
    End If

    nStart = crt.Screen.CurrentRow
    bDone = False
    dDeadline = Timer + timeoutSec

    Do
        n = crt.Screen.WaitForStrings(arrWait, 10, True)
        If n = 1 Or n = 2 Or n = 3 Then
            bDone = True
            Exit Do
        End If
        If n = 4 Then
            crt.Screen.Send " "
        End If
        If Timer > dDeadline Then
            Exit Do
        End If
    Loop

    ' 按行取屏（Screen.Get 不含行尾换行，逐行拼接）
    nEnd = crt.Screen.CurrentRow
    rawOut = ""
    For nRow = nStart To nEnd
        rawOut = rawOut & crt.Screen.Get(nRow, 1, nRow, 255) & vbCrLf
    Next

    WriteFileUtf8 prefix & "_raw.txt", rawOut

    If Not bDone Then
        WriteStatus prefix, ip, "FAIL", "指令执行超时(输出未在" & timeoutSec & "秒内结束，已保留屏幕现存内容供排查)", runId
        DisconnectQuietly
        Exit Sub
    End If

    ' 空输出检查：去掉提示符行后剩余内容过短视为无输出
    chk = Replace(rawOut, "<" & hostname & ">", "")
    chk = Replace(chk, "[" & hostname & "]", "")
    chk = Replace(chk, hostname & ">", "")
    If Len(Trim(chk)) < 10 Then
        WriteStatus prefix, ip, "FAIL", "输出为空", runId
        DisconnectQuietly
        Exit Sub
    End If

    WriteStatus prefix, ip, "SUCCESS", "", runId
    DisconnectQuietly
End Sub

Main
