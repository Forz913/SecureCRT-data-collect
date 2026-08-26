from pathlib import Path

from tool.parser import parse_output

SAMPLES = Path(__file__).parent.parent / "samples"


def read_sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def test_parses_single_alarm_with_wrapped_info():
    alarms = parse_output(read_sample("sample_1_normal.txt"))
    assert len(alarms) == 1
    a = alarms[0]
    assert a["index"] == "1"
    assert a["level"] == "Critical"
    assert a["date"] == "2023-04-28"
    assert a["time"] == "01:02:41+08:00"
    assert a["info"].startswith("PM7 POWER 25 is failed")
    assert "power supply became faulty" in a["info"]
    assert "OID:1.3.6.1.4" in a["info"]


def test_parses_multiple_alarms_with_levels():
    alarms = parse_output(read_sample("sample_2_multiple.txt"))
    assert [a["level"] for a in alarms] == ["Critical", "Major", "Warning"]
    assert len(alarms) == 3
    assert "exceeded the upper limit" in alarms[1]["info"]


def test_empty_table_returns_empty_list():
    assert parse_output(read_sample("sample_3_empty.txt")) == []


def test_more_markers_are_removed():
    alarms = parse_output(read_sample("sample_4_more.txt"))
    assert len(alarms) == 2
    assert alarms[1]["level"] == "Minor"
    assert "---- More ----" not in alarms[0]["info"]


def test_garbage_text_is_ignored():
    raw = "hello\nsome random text\n<host>\n"
    assert parse_output(raw) == []


def test_crlf_input_is_normalized():
    raw = read_sample("sample_1_normal.txt").replace("\n", "\r\n")
    assert parse_output(raw)[0]["level"] == "Critical"


def test_indented_footer_is_not_attached():
    raw = read_sample("sample_2_multiple.txt") + "  Total: 3 alarms\n"
    alarms = parse_output(raw)
    assert len(alarms) == 3
    assert "Total" not in alarms[-1]["info"]


def test_time_without_timezone_is_parsed():
    raw = (
        "disp alarm hardware\n"
        "--------------------------------------------------------------------------------\n"
        "Index  Level    Date       Time           Info\n"
        "--------------------------------------------------------------------------------\n"
        "1      Warning  2023-05-10 12:30:00 Board 3 temperature is high\n"
        "<host>\n"
    )
    alarms = parse_output(raw)
    assert len(alarms) == 1
    assert alarms[0]["time"] == "12:30:00"
