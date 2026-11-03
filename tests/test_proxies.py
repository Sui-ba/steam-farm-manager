"""Запись прокси в конфиги ASF: адрес без логина/пароля, учётка в отдельных полях."""

import json

from tests.harness import TMP

import asf_manager as asf
import proxy_check

PROXY = {"id": 1, "protocol": "socks5", "host": "gate.example.com", "port": 10978, "username": "user_1", "password": "p@ss:secret"}


def test_proxy_url_has_no_credentials():
    assert asf.proxy_url(PROXY) == "socks5://gate.example.com:10978"
    fields = asf.proxy_fields(PROXY)
    assert fields == {"WebProxy": "socks5://gate.example.com:10978", "WebProxyUsername": "user_1",
                      "WebProxyPassword": "p@ss:secret", "SteamProtocols": 4}
    assert asf._proxy_display(fields["WebProxy"]) == "gate.example.com:10978"


def test_write_bot_proxies(monkeypatch):
    folder = TMP / "asf"
    (folder / "config").mkdir(parents=True, exist_ok=True)
    cfg = folder / "config" / "bot1.json"
    cfg.write_text(json.dumps({"SteamLogin": "Demo", "Enabled": True, "WebProxy": "socks5://u:x@old:1"}), encoding="utf-8")
    monkeypatch.setattr(asf, "get_asf_dir", lambda: str(folder))
    monkeypatch.setattr(asf, "ipc_alive", lambda: False)
    res = asf.write_bot_proxies([("demo", asf.proxy_fields(PROXY)), ("nobody", asf.proxy_fields(PROXY))])
    assert res["updated"] == ["bot1"] and res["missing"] == ["nobody"]
    assert "secret" not in json.dumps(res)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["WebProxy"] == "socks5://gate.example.com:10978"
    assert data["WebProxyUsername"] == "user_1" and data["WebProxyPassword"] == "p@ss:secret"
    assert data["SteamProtocols"] == 4 and data["Enabled"] is True
    assert cfg.read_text(encoding="utf-8").startswith("{\n    ")
    res = asf.write_bot_proxies([("demo", asf.proxy_fields(PROXY))])
    assert res["updated"] == [] and res["skipped"] == ["bot1"]


def test_check_hides_password(monkeypatch):
    def boom(*a, **k):
        raise OSError("failed via socks5h://user_1:p%40ss%3Asecret@gate p@ss:secret")
    monkeypatch.setattr(proxy_check.requests, "get", boom)
    r = proxy_check.check_one(PROXY, timeout=1)
    assert r["ok"] is False and "secret" not in json.dumps(r)
