"""Several named keys for one provider. The password store is the conftest's fake."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from bettermarkitdown import cli, core, credentials, runs
from bettermarkitdown.config import FREE_RPM, Options, find_api_key, key_choice
from bettermarkitdown.credentials import SERVICE, SavedKey

KEY = "AIza-a-long-enough-test-key-one"
OTHER = "AIza-a-long-enough-test-key-two"


@pytest.fixture
def no_dotenv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bettermarkitdown.config.load_dotenv", lambda *a, **k: None)


@pytest.fixture
def two_keys(no_dotenv):
    credentials.store_key("gemini", KEY, "Free", "free")
    credentials.store_key("gemini", OTHER, "Paid", "paid")


def test_a_key_saved_before_names_existed_is_main_and_stays_in_use(isolated_keys, no_dotenv):
    isolated_keys.saved[(SERVICE, "gemini")] = KEY          # as 1.6.0 left it
    assert credentials.saved_keys("gemini") == [SavedKey("Main", "", True)]
    assert find_api_key("gemini") == (KEY, "password store")


def test_adding_a_named_key_to_an_old_key_keeps_both_and_the_old_one_in_use(
        isolated_keys, no_dotenv):
    isolated_keys.saved[(SERVICE, "gemini")] = KEY
    credentials.store_key("gemini", OTHER, "Paid", "paid")
    assert credentials.saved_keys("gemini") == [SavedKey("Main", "", True),
                                                SavedKey("Paid", "paid", False)]
    assert find_api_key("gemini")[0] == KEY
    assert isolated_keys.saved[(SERVICE, "gemini")] == KEY


def test_one_plain_key_leaves_the_store_exactly_as_before(isolated_keys, no_dotenv):
    credentials.store_key("gemini", KEY)
    assert isolated_keys.saved == {(SERVICE, "gemini"): KEY}


def test_the_first_key_goes_in_use_and_later_ones_never_do(two_keys):
    assert credentials.active_key("gemini").name == "Free"
    assert find_api_key("gemini")[0] == KEY


def test_saving_with_no_name_replaces_the_key_in_use_only(two_keys):
    credentials.store_key("gemini", "AIza-a-replacement-key-for-free")
    assert credentials.stored_key("gemini", "Free") == "AIza-a-replacement-key-for-free"
    assert credentials.stored_key("gemini", "Paid") == OTHER


def test_replacing_a_key_keeps_its_tier(two_keys):
    credentials.store_key("gemini", "AIza-a-replacement-key-for-free", "free")   # any case
    assert credentials.saved_keys("gemini")[0] == SavedKey("Free", "free", True)


def test_switching_keys(two_keys):
    credentials.use_key("gemini", "paid")
    assert find_api_key("gemini")[0] == OTHER
    assert credentials.active_key("gemini").name == "Paid"


def test_a_key_is_only_ever_read_by_its_own_provider(two_keys):
    assert credentials.saved_keys("openai") == []
    assert find_api_key("openai")[0] is None


def test_an_environment_key_still_wins_and_has_no_name_or_tier(two_keys, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-from-the-environment-now")
    assert find_api_key("gemini") == ("AIza-from-the-environment-now", "GEMINI_API_KEY")
    assert key_choice("gemini") == ("", "")


def test_forgetting_the_key_in_use_never_switches_to_another(two_keys):
    assert credentials.forget_key("gemini", "Free")
    assert credentials.active_key("gemini") is None
    assert find_api_key("gemini") == (None, "")
    assert [k.name for k in credentials.saved_keys("gemini")] == ["Paid"]
    credentials.use_key("gemini", "Paid")
    assert find_api_key("gemini")[0] == OTHER


def test_forgetting_another_key_leaves_the_one_in_use(two_keys):
    assert credentials.forget_key("gemini", "Paid")
    assert find_api_key("gemini")[0] == KEY


def test_forgetting_a_provider_leaves_nothing_in_the_store(two_keys, isolated_keys):
    credentials.store_key("openai", "sk-another-providers-test-key")
    assert credentials.forget_key("gemini")
    assert not [account for _, account in isolated_keys.saved if account.startswith("gemini")]
    assert credentials.saved_keys("openai")


def test_key_forget_all_finds_every_named_key_without_the_settings_file(
        two_keys, isolated_keys, capsys):
    assert cli.main(["key", "forget", "all"]) == 0
    assert isolated_keys.saved == {}


def test_a_forgotten_key_and_a_missing_name_are_reported(two_keys):
    assert not credentials.forget_key("gemini", "Nope")
    with pytest.raises(ValueError, match="No saved key"):
        credentials.use_key("gemini", "Nope")
    with pytest.raises(ValueError, match="No saved key"):
        credentials.set_tier("gemini", "Nope", "free")


@pytest.mark.parametrize("name", ["", "   ", "a#b", "x" * 31, "a/b", "../x"])
def test_bad_names_are_refused(name, no_dotenv):
    with pytest.raises(ValueError):
        credentials.clean_name(name)


def test_a_damaged_index_falls_back_to_the_old_key(isolated_keys, no_dotenv):
    isolated_keys.saved[(SERVICE, "gemini")] = KEY
    isolated_keys.saved[(SERVICE, "gemini:#keys")] = "not json"
    assert find_api_key("gemini")[0] == KEY


def test_no_key_value_ever_goes_in_the_list_of_names(two_keys, isolated_keys):
    assert KEY not in isolated_keys.saved[(SERVICE, "gemini:#keys")]


# --- what a run costs -------------------------------------------------------------------

def test_a_free_key_costs_nothing_and_a_paid_key_keeps_the_list_price(tmp_path):
    common = dict(pdf=tmp_path / "a.pdf", output=tmp_path / "a.md", model="gemini-3.6-flash")
    assert Options(**common, key_tier="free").prices() == (0.0, 0.0)
    assert Options(**common, key_tier="paid").prices() != (0.0, 0.0)
    assert Options(**common).prices() != (0.0, 0.0), "an unlabelled key is never assumed free"


def run_a_scanned_book(tier, tmp_path, monkeypatch, budget):
    from tests.test_workspace import make_pdf

    def describe(client, model, png, prompt, **kwargs):
        kwargs["meter"].add(SimpleNamespace(prompt_tokens=50000, completion_tokens=50000,
                                            total_tokens=100000))
        return "A page of text that the model read."

    monkeypatch.setattr(core, "describe_image", describe)
    pdf = make_pdf(tmp_path / "book.pdf", text_pages=0, scanned_pages=3)
    return core.convert(Options(pdf=pdf, output=tmp_path / "book.md", provider="gemini",
                                model="gemini-3.6-flash", api_key=KEY, key_tier=tier,
                                budget_usd=budget, workers=1, rpm=0, ocr_fallback=False))


@pytest.mark.parametrize("tier", ["", "paid", "free"])
def test_a_spending_cap_stops_a_run_whatever_the_key_is_marked(tier, tmp_path, monkeypatch):
    result = run_a_scanned_book(tier, tmp_path, monkeypatch, budget=0.01)
    assert result.stopped_reason == "budget" and result.pages_converted < 3


def test_a_key_marked_free_shows_as_free_even_when_the_cap_stops_it(tmp_path, monkeypatch):
    assert run_a_scanned_book("free", tmp_path, monkeypatch, budget=0.01).cost == 0


def test_no_cap_lets_a_key_marked_free_finish(tmp_path, monkeypatch):
    result = run_a_scanned_book("free", tmp_path, monkeypatch, budget=0)
    assert result.stopped_reason == "" and result.pages_converted == 3


def test_a_price_the_person_gives_counts_for_the_cap_too(tmp_path):
    common = dict(pdf=tmp_path / "a.pdf", output=tmp_path / "a.md", model="gemini-3.6-flash",
                  price_in=1.0, price_out=2.0)
    assert Options(**common, key_tier="free").list_prices() == (1.0, 2.0)


def test_a_key_marked_free_goes_slowly_and_says_how_long(two_keys, monkeypatch, tmp_path):
    from tests.test_workspace import make_pdf

    monkeypatch.setenv("BMID_PROVIDER", "gemini")
    pdf = make_pdf(tmp_path / "book.pdf", text_pages=0, scanned_pages=3)
    opts = runs.options(runs.plan(), source=pdf, output=tmp_path / "book.md")
    assert (opts.workers, opts.rpm) == (1, FREE_RPM)
    assert runs.inspect_file(pdf)["estimate"] == {
        "requests": 3, "cost": 0.0, "seconds": 3 * 60 / FREE_RPM}

    credentials.use_key("gemini", "Paid")
    opts = runs.options(runs.plan(), source=pdf, output=tmp_path / "book.md")
    assert (opts.workers, opts.rpm) == (3, 60)
    assert runs.inspect_file(pdf)["estimate"]["seconds"] is None


def run_from_the_command_line(monkeypatch, tmp_path, args, stopped=""):
    seen = []

    def fake_convert(opts, on_event=None):
        seen.append(opts)
        opts.output.write_text("x", "utf-8")
        return core.Result(output=opts.output, pages_total=3, pages_selected=3,
                           pages_converted=1, stopped_reason=stopped)

    monkeypatch.setattr(core, "convert", fake_convert)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    cli.main([str(pdf), "--provider", "gemini", *args])
    return seen[0]


def test_cli_paces_a_free_key_unless_told_otherwise(two_keys, monkeypatch, tmp_path):
    opts = run_from_the_command_line(monkeypatch, tmp_path, ["--use-key", "Free"])
    assert (opts.workers, opts.rpm) == (1, FREE_RPM)
    opts = run_from_the_command_line(monkeypatch, tmp_path, ["--use-key", "Paid"])
    assert (opts.workers, opts.rpm) == (3, 60)
    opts = run_from_the_command_line(monkeypatch, tmp_path, ["--use-key", "Free", "--rpm", "30",
                                                             "--workers", "2"])
    assert (opts.workers, opts.rpm) == (2, 30)


def test_cli_says_the_cap_counted_at_list_price_on_a_free_key(
        two_keys, monkeypatch, tmp_path, capsys):
    run_from_the_command_line(monkeypatch, tmp_path, ["--use-key", "Free", "--budget-usd", "1"],
                              stopped="budget")
    assert "list price" in capsys.readouterr().out
    run_from_the_command_line(monkeypatch, tmp_path, ["--use-key", "Paid", "--budget-usd", "1"],
                              stopped="budget")
    assert "list price" not in capsys.readouterr().out


def test_the_engine_says_which_key_a_run_will_use(two_keys, monkeypatch):
    from bettermarkitdown.runs import engine

    monkeypatch.setenv("BMID_PROVIDER", "gemini")
    status = engine()
    assert (status["key_name"], status["key_tier"], status["per_call"]) == ("Free", "free", 0.0)
    credentials.use_key("gemini", "Paid")
    status = engine()
    assert status["key_name"] == "Paid" and status["per_call"] > 0


def test_the_engine_asks_for_a_choice_when_no_key_is_in_use(two_keys, monkeypatch):
    from bettermarkitdown.runs import engine

    monkeypatch.setenv("BMID_PROVIDER", "gemini")
    credentials.forget_key("gemini", "Free")
    status = engine()
    assert not status["ready"] and "Choose which" in status["problem"]


# --- the command line -------------------------------------------------------------------

def test_cli_adds_lists_switches_and_marks_keys(no_dotenv, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(KEY + "\n" + OTHER + "\n"))
    assert cli.main(["key", "set", "gemini", "--name", "Free", "--tier", "free", "--stdin"]) == 0
    assert cli.main(["key", "set", "gemini", "--name", "Paid", "--stdin"]) == 0
    assert "not in use yet" in capsys.readouterr().out
    assert cli.main(["key", "tier", "gemini", "--name", "Paid", "--tier", "paid"]) == 0
    assert cli.main(["key", "use", "gemini", "--name", "Paid"]) == 0
    assert "costs money" in capsys.readouterr().out
    assert cli.main(["key", "status"]) == 0
    out = capsys.readouterr().out
    assert "Free" in out and "Paid" in out and "in use" in out
    assert KEY not in out and OTHER not in out


def test_cli_refuses_a_free_tier_on_a_provider_without_one(no_dotenv, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(KEY + "\n"))
    assert cli.main(["key", "set", "openai", "--tier", "free", "--stdin"]) == 1
    assert credentials.saved_keys("openai") == []


def test_cli_will_not_guess_which_key_to_forget(two_keys, capsys):
    assert cli.main(["key", "forget", "gemini"]) == 1
    assert "Free, Paid" in capsys.readouterr().err
    assert len(credentials.saved_keys("gemini")) == 2


def test_use_key_applies_to_one_run_and_changes_nothing_saved(two_keys, monkeypatch, tmp_path):
    captured = {}

    def fake_convert(opts, on_event=None):
        captured["opts"] = opts
        raise KeyboardInterrupt

    monkeypatch.setattr(core, "convert", fake_convert)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert cli.main([str(pdf), "--provider", "gemini", "--use-key", "Paid"]) == 130
    opts = captured["opts"]
    assert (opts.api_key, opts.key_name, opts.key_tier) == (OTHER, "Paid", "paid")
    assert credentials.active_key("gemini").name == "Free"


def test_use_key_with_an_unknown_name_fails_before_any_work(
        two_keys, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(core, "convert", lambda *a, **k: pytest.fail("must not run"))
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert cli.main([str(pdf), "--provider", "gemini", "--use-key", "Nope"]) == 1
    assert "key status" in capsys.readouterr().err


def run_that_hits_the_daily_limit(monkeypatch, tmp_path, args):
    def fake_convert(opts, on_event=None):
        opts.output.write_text("x", "utf-8")
        return core.Result(output=opts.output, pages_total=3, pages_selected=3,
                           pages_converted=1, stopped_reason="DailyQuotaExceeded")

    monkeypatch.setattr(core, "convert", fake_convert)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    return cli.main([str(pdf), "--provider", "gemini", *args])


def test_at_the_daily_limit_the_run_offers_the_other_key_and_does_not_switch(
        two_keys, monkeypatch, tmp_path, capsys):
    assert run_that_hits_the_daily_limit(monkeypatch, tmp_path, []) == 2
    out = capsys.readouterr().out
    assert '--use-key "Paid"' in out and "costs money" in out
    assert credentials.active_key("gemini").name == "Free"


def test_going_back_to_a_free_key_says_what_that_means(two_keys, monkeypatch, tmp_path, capsys):
    credentials.use_key("gemini", "Paid")
    assert run_that_hits_the_daily_limit(monkeypatch, tmp_path, []) == 2
    assert "may use your documents" in capsys.readouterr().out


# --- the app ----------------------------------------------------------------------------

def call(app, method, path, body=None):
    from tests.test_app import call as real
    return real(app, method, path, body)


def test_app_adds_keys_without_changing_the_one_in_use(app, monkeypatch, no_dotenv):
    from bettermarkitdown.app import api

    monkeypatch.setattr(api, "list_models", lambda key, url, provider=None: ["m1"])
    assert call(app, "POST", "/api/key", {"provider": "gemini", "key": KEY, "name": "Free",
                                          "tier": "free"})[0] == 200
    assert call(app, "POST", "/api/key", {"provider": "gemini", "key": OTHER, "name": "Paid",
                                          "tier": "paid"})[0] == 200
    _, state = call(app, "GET", "/api/state")
    gemini = next(p for p in state["providers"] if p["id"] == "gemini")
    assert [(k["name"], k["tier"], k["active"]) for k in gemini["keys"]] == [
        ("Free", "free", True), ("Paid", "paid", False)]
    assert "may use your documents" in gemini["keys"][0]["note"]
    text = json.dumps(state)
    assert KEY not in text and OTHER not in text


def test_app_switches_marks_and_forgets_keys(app, two_keys):
    assert call(app, "POST", "/api/key/use", {"provider": "gemini", "name": "Paid"})[0] == 200
    assert credentials.active_key("gemini").name == "Paid"
    assert call(app, "POST", "/api/key/tier",
                {"provider": "gemini", "name": "Paid", "tier": ""})[0] == 200
    assert credentials.named_key("gemini", "Paid").tier == ""
    assert call(app, "POST", "/api/key/forget", {"provider": "gemini", "name": "Paid"})[0] == 200
    assert credentials.active_key("gemini") is None
    assert [k.name for k in credentials.saved_keys("gemini")] == ["Free"]


def test_app_refuses_an_unknown_key_a_bad_tier_and_a_free_tier_it_does_not_have(app, two_keys):
    assert call(app, "POST", "/api/key/use", {"provider": "gemini", "name": "Nope"})[0] == 400
    assert call(app, "POST", "/api/key/tier",
                {"provider": "gemini", "name": "Free", "tier": "cheap"})[0] == 400
    assert call(app, "POST", "/api/key",
                {"provider": "openai", "key": KEY, "tier": "free"})[0] == 400
