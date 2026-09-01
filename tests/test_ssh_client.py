import paramiko

from tool.ssh_client import is_algorithm_error


def test_algorithm_error_detection():
    assert is_algorithm_error(paramiko.SSHException("Unable to agree on host key algorithm"))
    assert is_algorithm_error(paramiko.SSHException("no matching key exchange method"))
    assert is_algorithm_error(paramiko.SSHException("kex protocol error"))
    assert not is_algorithm_error(paramiko.SSHException("Connection reset by peer"))
    assert not is_algorithm_error(paramiko.SSHException("timeout"))
