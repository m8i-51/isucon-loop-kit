from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from isuctl.ansible_run import AnsibleError
from isuctl.cli import app
from isuctl.deploy import DeployBlockedError, run_check, run_deploy, run_provision


def test_deploy_requires_branch():
    with pytest.raises(DeployBlockedError, match="branch"):
        run_deploy(None, branch="")


def test_deploy_rejects_blank_branch():
    with pytest.raises(DeployBlockedError, match="branch"):
        run_deploy(None, branch="   ")


def test_deploy_calls_ansible_playbook():
    with patch("isuctl.deploy.run_playbook") as play:
        run_deploy(None, branch="feat/x", limit="s1,s2")
    play.assert_called_once_with(
        "deploy.yml", extra_vars={"branch": "feat/x"}, limit="s1,s2"
    )


def test_deploy_strips_branch_and_ignores_legacy_kwargs():
    with patch("isuctl.deploy.run_playbook") as play:
        run_deploy(
            None,
            branch="  main  ",
            force=True,
            restart_unit="ignored.service",
        )
    play.assert_called_once_with(
        "deploy.yml", extra_vars={"branch": "main"}, limit=None
    )


def test_deploy_wraps_ansible_error():
    with (
        patch("isuctl.deploy.run_playbook", side_effect=AnsibleError("boom")),
        pytest.raises(DeployBlockedError, match="boom"),
    ):
        run_deploy(None, branch="main")


def test_check_and_provision_call_playbooks():
    with patch("isuctl.deploy.run_playbook") as play:
        run_check(limit="s1")
        run_provision()
    assert play.call_args_list[0].args == ("check.yml",)
    assert play.call_args_list[0].kwargs == {"limit": "s1"}
    assert play.call_args_list[1].args == ("init.yml",)
    assert play.call_args_list[1].kwargs == {"limit": None}


def test_check_wraps_ansible_error():
    with (
        patch("isuctl.deploy.run_playbook", side_effect=AnsibleError("nope")),
        pytest.raises(DeployBlockedError, match="nope"),
    ):
        run_check()


def test_cli_deploy_requires_branch():
    result = CliRunner().invoke(app, ["deploy"])
    assert result.exit_code != 0


def test_cli_deploy_command():
    with patch("isuctl.cli.run_deploy") as run_deploy_mock:
        result = CliRunner().invoke(
            app, ["deploy", "--branch", "main", "--limit", "s1"]
        )
    assert result.exit_code == 0
    assert "デプロイ完了 branch=main" in result.stdout
    run_deploy_mock.assert_called_once_with(None, branch="main", limit="s1")


def test_cli_deploy_reports_failure():
    with patch(
        "isuctl.cli.run_deploy",
        side_effect=DeployBlockedError("ansible-playbook が失敗しました"),
    ):
        result = CliRunner().invoke(app, ["deploy", "--branch", "main"])
    assert result.exit_code == 1
    assert "失敗しました" in result.stdout


def test_cli_check_and_provision():
    with patch("isuctl.cli.run_check") as check_mock:
        r1 = CliRunner().invoke(app, ["check", "--limit", "s2"])
    with patch("isuctl.cli.run_provision") as prov_mock:
        r2 = CliRunner().invoke(app, ["provision"])
    assert r1.exit_code == 0
    assert r2.exit_code == 0
    check_mock.assert_called_once_with(limit="s2")
    prov_mock.assert_called_once_with(limit=None)
