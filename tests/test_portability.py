from pathlib import Path
import pytest
from radar.storage import Store
from radar import cli


def test_fresh_vault_setting_uses_current_home_or_environment(tmp_path, monkeypatch):
    monkeypatch.delenv('ARXIV_RADAR_VAULT', raising=False)
    s = Store(tmp_path / 'data')
    assert s.settings()['vault_path'] == str(Path.home() / 'Obsidian' / 'paper-vault')
    target = tmp_path / 'my vault'
    monkeypatch.setenv('ARXIV_RADAR_VAULT', str(target))
    assert s.settings()['vault_path'] == str(target)
    s.set_setting('vault_path', str(tmp_path / 'saved'))
    assert s.settings()['vault_path'] == str(tmp_path / 'saved')


def test_configure_accepts_existing_vault_without_writing_it(tmp_path, monkeypatch, capsys):
    vault = tmp_path / 'another vault'
    vault.mkdir()
    note = vault / 'keep.md'
    note.write_text('personal note', encoding='utf-8')
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['radar', 'configure', '--vault', str(vault)])
    assert cli.main() == 0
    assert Store(tmp_path / 'data').settings()['vault_path'] == str(vault)
    assert note.read_text() == 'personal note'
    assert list(vault.iterdir()) == [note]
    assert str(vault) in capsys.readouterr().out


def test_configure_rejects_missing_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['radar', 'configure', '--vault', str(tmp_path / 'missing')])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert not (tmp_path / 'missing').exists()
