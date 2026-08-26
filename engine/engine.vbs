' engine.vbs - SecureCRT 批量取数引擎（每进程一台服务器）
' 用法: SecureCRT.exe /SCRIPT engine.vbs /ARG <任务文件绝对路径>
' 任务文件: UTF-8，每行一个字段，共 8 行:
'   IP / 主机名 / 账号 / 密码 / 超时秒数 / 查询指令 / 结果文件前缀(绝对路径) / 停止标志文件(绝对路径)
' 输出: <前缀>_raw.txt（原始屏幕输出）、<前缀>_status.txt（IP<TAB>状态<TAB>原因）
' 状态: SUCCESS / FAIL / STOPPED
' 注意: 不使用 crt.Quit —— SecureCRT 单实例，Quit 会关掉用户自己的窗口
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

Sub WriteStatus(strPrefix, strIp, strStatus, strReason)
    WriteFileUtf8 strPrefix & "_status.txt", strIp & vbTab & strStatus & vbTab & strReason
End Sub

Sub DisconnectQuietly()
    On Error Resume Next
    crt.Session.Disconnect
    On Error GoTo 0
End Sub

Sub Main()
    Dim taskPath, content, lines
    Dim ip, hostname, user, passwd
    Dim timeoutSec, command, prefix, stopFlagPath
    Dim n, rawOut

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
    If UBound(lines) < 7 Then
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

    If g_fso.FileExists(stopFlagPath) Then
        WriteStatus prefix, ip, "STOPPED", "用户停止"
        Exit Sub
    End If

    On Error Resume Next
    crt.Session.Connect "/SSH2 /ACCEPTHOSTKEYS /L " & user & " /PASSWORD """ & passwd & """ " & ip
    On Error GoTo 0

    n = crt.Screen.WaitForString("<", 30)
    If Not n Then
        WriteStatus prefix, ip, "FAIL", "连接后30秒未出现命令提示符(连接失败/认证失败/不可达)"
        DisconnectQuietly
        Exit Sub
    End If

    crt.Screen.Send "screen-length 0 temporary" & vbCr
    n = crt.Screen.WaitForString("<", 15)
    If Not n Then
        WriteStatus prefix, ip, "FAIL", "关闭分页后未回到命令提示符"
        DisconnectQuietly
        Exit Sub
    End If

    crt.Screen.Send command & vbCr
    rawOut = crt.Screen.ReadString("<[^\s>]+>", timeoutSec)

    If rawOut = "" Then
        n = crt.Screen.WaitForString("<", 2)
        If n Then
            WriteStatus prefix, ip, "FAIL", "输出捕获异常"
        Else
            WriteStatus prefix, ip, "FAIL", "指令执行超时(" & timeoutSec & "秒)"
        End If
        DisconnectQuietly
        Exit Sub
    End If

    WriteFileUtf8 prefix & "_raw.txt", rawOut

    If Len(Trim(Replace(rawOut, command, ""))) < 10 Then
        WriteStatus prefix, ip, "FAIL", "输出为空"
        DisconnectQuietly
        Exit Sub
    End If

    WriteStatus prefix, ip, "SUCCESS", ""
    DisconnectQuietly
End Sub

Main
