from tool.locate import find_securecrt


def test_returns_second_candidate_when_first_missing():
    def fake_exists(p: str) -> bool:
        return p == r"C:\Program Files (x86)\VanDyke Software\Clients\SecureCRT.exe"
    found = find_securecrt(exists=fake_exists, registry_lookup=lambda: "")
    assert found == r"C:\Program Files (x86)\VanDyke Software\Clients\SecureCRT.exe"


def test_uses_registry_path_when_no_candidate_exists():
    def fake_exists(p: str) -> bool:
        return p == r"D:\Apps\SecureCRT\SecureCRT.exe"
    found = find_securecrt(exists=fake_exists,
                           registry_lookup=lambda: r"D:\Apps\SecureCRT")
    assert found == r"D:\Apps\SecureCRT\SecureCRT.exe"


def test_returns_empty_when_not_found():
    found = find_securecrt(exists=lambda p: False, registry_lookup=lambda: "")
    assert found == ""
