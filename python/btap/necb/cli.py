"""The command-line face of performance_compliance (port of btap-necb's
cli.rb): one .osm in, a verdict + EUIs + a self-contained HTML report out.

All logic lives here rather than in the console-script shim so it is testable
IN-PROCESS against io.StringIO — a subprocess test of a 40-minute pipeline is
not a test anyone runs. ``run`` returns an int and never calls exit; ``main``
(the console script) does that, via ``os._exit`` (Ruby ``exit!``) after
flushing."""

from __future__ import annotations

import argparse
import glob as _glob
import json
import os
import sys
import threading
import time
from datetime import date
from pathlib import Path

from btap._compat import opt, ruby_round, ruby_str

#: Exit codes are load-bearing: "your building fails the code", "your file is
#: not NECB-tagged" and "EnergyPlus crashed" have three different fixes, and a
#: demo audience hits all three. Collapsing them into 1 would be a lie.
EXIT = {
    "compliant": 0,        # 8.4.1.2 satisfied
    "not_compliant": 1,    # a VERDICT, not an error
    "usage": 2,            # bad flag, missing file, unresolvable HDD
    "preflight": 3,        # the model was rejected before any simulation ran
    "simulation": 4,       # EnergyPlus severe/fatal, or no engine
    "internal": 5,         # anything unanticipated
    "no_determination": 6,  # --quick, --simulate sizing|none, or compliant None
}

QUICK_RUN_PERIOD = {"begin_month": 1, "begin_day": 1, "end_month": 1,
                    "end_day": 7}


class _UsageError(Exception):
    """Every parse/validation problem funnels here (Ruby: the OptionParser
    rescue + the validate() string returns)."""


class _Parser(argparse.ArgumentParser):
    """argparse that RAISES instead of exiting — ``run`` owns the exit
    code."""

    def error(self, message):
        raise _UsageError(message)


def run(argv, out=None, err=None):
    """:return: an EXIT code int; never raises, never exits."""
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    o, early = parse(argv, out, err)
    if early is not None:
        return early

    backend_problem = select_backend(o)
    if backend_problem:
        print(f"ERROR: {backend_problem}", file=err)
        return EXIT["usage"]

    ticker = None
    if not (o.get("quiet") or o.get("json")):
        ticker = Progress.start(o["run_dir"], out)
    try:
        from btap.necb.compliance import (
            PreflightError,
            performance_compliance,
        )
        try:
            model, kwargs = compliance_kwargs(o)
            result = performance_compliance(model, **kwargs)
            Progress.stop(ticker)
            emit(result, o, out)
            return verdict_exit(result)
        except PreflightError as e:
            Progress.stop(ticker)
            preflight_help(e, o, err)
            return EXIT["preflight"]
        except ValueError as e:
            Progress.stop(ticker)
            print(f"ERROR: {e}", file=err)
            return EXIT["usage"]
        except Exception as e:
            Progress.stop(ticker)
            # The Local backend already extracts the E+ severe/fatal blocks
            # and names the log; reprint it verbatim rather than paraphrasing
            # it worse.
            message = str(e)
            simulation = "EnergyPlus" in message or "openstudio CLI" in message
            print(f"ERROR: {message}", file=err)
            note = audit_note(o.get("run_dir"))
            if note:
                print(note, file=err)
            return EXIT["simulation"] if simulation else EXIT["internal"]
    finally:
        Progress.stop(ticker)


# ---------------------------------------------------------------- parsing

def parse(argv, out, err):
    """:return: (options, None) or (None, early exit code)"""
    o = {"vintage": "2020", "simulate": "annual", "report_html": True,
         "backend": "local", "report_options": {}, "necb_loads": {}}
    parser = build_parser()
    try:
        namespace, rest = parser.parse_known_args(list(argv))
        unknown_flags = [a for a in rest if a.startswith("-")]
        if unknown_flags:
            raise _UsageError(f"invalid option: {' '.join(unknown_flags)}")
    except argparse.ArgumentError as e:
        # exit_on_error=False surfaces bad values (e.g. an unknown --vintage)
        # as ArgumentError instead of routing them through Parser.error.
        print(f"ERROR: {e}", file=err)
        print(parser.format_help(), file=err)
        return None, EXIT["usage"]
    except _UsageError as e:
        print(f"ERROR: {e}", file=err)
        print(parser.format_help(), file=err)
        return None, EXIT["usage"]

    if namespace.help:
        print(parser.format_help(), file=out)
        return None, EXIT["compliant"]
    if namespace.version:
        print(f"btap-compliance {_version()}", file=out)
        return None, EXIT["compliant"]

    _collect(o, namespace)

    # Informational, like --help: answering "what weather do I have?" must
    # not require a model the user has not chosen yet.
    if o.get("list_cities"):
        print(Weather.catalogue_text(), file=out)
        return None, EXIT["compliant"]

    o["model"] = rest.pop(0) if rest else None
    if not o["model"]:
        print("ERROR: no model given.", file=err)
        print(parser.format_help(), file=err)
        return None, EXIT["usage"]
    if rest:
        print(f"ERROR: unexpected extra argument(s): {' '.join(rest)}",
              file=err)
        return None, EXIT["usage"]

    problem = Weather.resolve(o) or validate(o)
    if problem:
        print(f"ERROR: {problem}", file=err)
        return None, EXIT["usage"]
    if not o.get("run_dir"):
        stem = Path(o["model"]).stem
        o["run_dir"] = os.path.join(os.getcwd(), f"necb_run_{stem}")
    return o, None


def build_parser():
    p = _Parser(
        prog="btap-compliance", add_help=False, exit_on_error=False,
        usage="btap-compliance MODEL.osm --epw FILE [options]",
        description=("NECB Part 8 performance-path compliance: runs the "
                     "proposed and reference\nbuildings and reports the "
                     "8.4.1.2 determination."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--epw", metavar="PATH",
                   help="weather file (required unless --simulate none)")
    p.add_argument("--ddy", metavar="PATH",
                   help="design-day file (default: the .ddy beside --epw)")
    p.add_argument("--hdd", type=float, metavar="N",
                   help="heating degree-days (default: from the EPW site)")
    p.add_argument("--city", metavar="NAME",
                   help="bundled/cached city instead of --epw "
                        "(--list-cities to see them)")
    p.add_argument("--list-cities", action="store_true",
                   help="list the weather files this install carries")
    p.add_argument("-o", "--out", dest="run_dir", metavar="DIR",
                   help="run directory (default: ./necb_run_<model>)")
    p.add_argument("--vintage", choices=["2020", "2025"], default="2020",
                   help="NECB vintage: 2020 or 2025 (default 2020)")
    p.add_argument("--storeys", type=int, metavar="N",
                   help="above-ground storey count override")
    p.add_argument("--simulate", choices=["annual", "sizing", "none"],
                   default="annual", help="annual (default), sizing, or none")
    p.add_argument("--quick", action="store_true",
                   help="one-week run period - NOT a code determination")
    p.add_argument("--backend", choices=["local", "remote"], default="local",
                   help="local (default) or remote")
    p.add_argument("--no-report", dest="report_html", action="store_false",
                   help="skip the HTML report")
    p.add_argument("--json", action="store_true",
                   help="machine-readable output on stdout")
    p.add_argument("--quiet", action="store_true", help="no progress ticker")

    group = p.add_argument_group(
        "space types - required when the model is not already NECB-tagged")
    group.add_argument("--space-type", metavar="SPEC",
                       help='"BuildingType/SpaceType" applied to every '
                            "floor-area space")
    group.add_argument("--space-type-map", metavar="FILE",
                       help='JSON {"space name": ["BuildingType","SpaceType"]}')
    group.add_argument("--shw-fuel", metavar="FUEL",
                       help="service-water fuel, e.g. NaturalGas")
    group.add_argument("--hvac-system", metavar="NAME",
                       help="proposed HVAC from the catalog")

    costing = p.add_argument_group(
        "costing - priced tables are not shipped; point at your own")
    costing.add_argument("--costs-csv", metavar="PATH",
                         help="licensed unit-cost table")

    header = p.add_argument_group("report header")
    for flag in ("project", "address", "permit", "prepared-by", "por", "date"):
        header.add_argument(f"--{flag}", metavar="VALUE")

    p.add_argument("-h", "--help", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--version", action="store_true", help=argparse.SUPPRESS)
    return p


#: report-header flag -> report_options key (Ruby's flag map)
_HEADER_KEYS = {"project": "project_name", "address": "address",
                "permit": "permit_number", "prepared_by": "prepared_by",
                "por": "professional_of_record", "date": "date"}


def _collect(o, namespace):
    """argparse namespace -> the Ruby-shaped options dict."""
    ns = vars(namespace)
    for key in ("epw", "ddy", "hdd", "city", "run_dir", "vintage", "storeys",
                "simulate", "quick", "backend", "report_html", "json", "quiet",
                "space_type", "space_type_map", "costs_csv"):
        if ns.get(key) is not None:
            o[key] = ns[key]
    o["list_cities"] = bool(ns.get("list_cities"))
    if ns.get("shw_fuel"):
        o["necb_loads"]["shw_fuel"] = ns["shw_fuel"]
    if ns.get("hvac_system"):
        o["necb_loads"]["hvac_system"] = ns["hvac_system"]
    for flag, key in _HEADER_KEYS.items():
        if ns.get(flag):
            o["report_options"][key] = ns[flag]


def _version():
    try:
        from importlib.metadata import version
        return version("btap")
    except Exception:
        return "dev"


def validate(o):
    """Everything catchable BEFORE the model load. The pipeline's weather
    guard raises for a missing epw/ddy too, but only after the load — a user
    who fat-fingered a path should not wait for that.
    :return: an error message, or None"""
    if not os.path.exists(str(o.get("model"))):
        return f"model not found: {o.get('model')}"

    # Supplied FILE arguments are checked in EVERY mode: these used to sit
    # after the --simulate none early return, so a fat-fingered
    # --space-type-map under none-mode sailed past validation into file I/O
    # and surfaced as exit 5 (internal) instead of the documented usage exit
    # 2. Fixed Ruby-first (found by review, 2026-08-28).
    if o.get("costs_csv") and not os.path.exists(o["costs_csv"]):
        return f"costs csv not found: {o['costs_csv']}"
    if o.get("space_type_map") and not os.path.exists(o["space_type_map"]):
        return f"space-type map not found: {o['space_type_map']}"
    if o["simulate"] == "none":
        return None

    if not o.get("epw"):
        return "no --epw given (required unless --simulate none)"
    if not os.path.exists(o["epw"]):
        return f"epw not found: {o['epw']}"

    if not o.get("ddy"):
        stem, ext = os.path.splitext(o["epw"])
        o["ddy"] = stem + ".ddy" if ext.lower() == ".epw" else o["epw"]
    if not os.path.exists(o["ddy"]):
        return (f"ddy not found: {o['ddy']}\n       "
                "a design-day file is required; pass --ddy explicitly if it "
                "is not beside the .epw")

    return None


# ------------------------------------------------------------- marshalling

def compliance_kwargs(o):
    """:return: (model, kwargs) — `model` is positional on
    performance_compliance, so it cannot ride in the kwargs dict."""
    kw = {"vintage": o["vintage"], "run_dir": o["run_dir"],
          "simulate": o["simulate"], "report_html": o["report_html"],
          "report_options": default_report_options(o)}
    if o.get("epw"):
        kw["weather"] = {"epw": o["epw"], "ddy": o["ddy"]}
    if o.get("hdd") is not None:
        kw["hdd"] = o["hdd"]
    if o.get("storeys") is not None:
        kw["building"] = {"storeys": o["storeys"]}
    if o.get("quick"):
        kw["run_period"] = dict(QUICK_RUN_PERIOD)
    if o.get("costs_csv"):
        kw["costs_csv"] = o["costs_csv"]
        kw["costing"] = True
    loads = necb_loads(o)
    if loads:
        kw["necb_loads"] = loads
    return model_argument(o), kw


def model_argument(o):
    """A path string is enough UNLESS we have to enumerate space names to
    build the map, in which case load once here and hand over the Model — the
    pipeline's loader takes either, and this avoids a second
    VersionTranslator pass."""
    if not o.get("space_type"):
        return o["model"]

    # Memoized on the options dict: necb_loads calls this to enumerate space
    # names and compliance_kwargs calls it again for the pipeline argument —
    # without the memo the "load once" contract above was a comment, not a
    # behaviour, and the VersionTranslator ran twice. Fixed Ruby-first
    # (found by review, 2026-08-28).
    if "_loaded_model" in o:
        return o["_loaded_model"]

    import openstudio

    translator = openstudio.osversion.VersionTranslator()
    model = opt(translator.loadModel(openstudio.path(o["model"])))
    if model is None:
        raise ValueError(f"input model could not be loaded: {o['model']}")
    o["_loaded_model"] = model
    return model


def necb_loads(o):
    if o.get("space_type_map"):
        with open(o["space_type_map"], encoding="utf-8") as handle:
            map_ = json.load(handle)
    elif o.get("space_type"):
        bt, _, st = o["space_type"].partition("/")
        if not st:
            raise ValueError('--space-type must be "BuildingType/SpaceType"')

        # partofTotalFloorArea matches what the pre-flight checks; mapping
        # plenums would be noise the pre-flight ignores anyway.
        model = model_argument(o)
        map_ = {s.nameString(): [bt, st] for s in model.getSpaces()
                if s.partofTotalFloorArea()}
    else:
        map_ = None
    if map_ is None:
        return None

    return {**o["necb_loads"], "space_type_map": map_}


def default_report_options(o):
    ro = dict(o["report_options"])
    ro.setdefault("date", date.today().strftime("%Y-%m-%d"))
    ro.setdefault("project_name", Path(o["model"]).stem)
    return ro


def select_backend(o):
    """``performance_compliance`` takes no backend: the umbrella calls
    run_energyplus at ~8 sites, so the selection is a process-wide default set
    once here rather than a parameter threaded through every phase.
    :return: an error message, or None on success"""
    if o.get("backend") != "remote":
        # cli.run is in-process API by design (the suites call it
        # repeatedly): a previous run's remote selection must not leak into
        # a later local run, so local EXPLICITLY resets the process-wide
        # default rather than assuming it. Fixed on both sides (found by
        # review, 2026-08-28).
        from btap.simulation import runner

        runner.set_default_backend(None)
        return None

    from btap.simulation import Remote, runner

    remote = Remote()
    if not remote.is_configured():
        return ("--backend remote needs HBIX_SIM_ENDPOINT and HBIX_API_KEY "
                "in the environment")

    runner.set_default_backend(remote)
    return None


# ---------------------------------------------------------------- output

def verdict_exit(result):
    """A shortened run still returns a boolean from the pipeline's evaluate
    (it only sets report['annual'] = False and warns), so the CLI must refuse
    to print a verdict rather than pass a week-long run off as a
    determination."""
    if result.compliant is None:
        return EXIT["no_determination"]
    if result.report.get("annual") is False:
        return EXIT["no_determination"]

    return EXIT["compliant"] if result.compliant else EXIT["not_compliant"]


def emit(result, o, out):
    if o.get("json"):
        print(json.dumps(json_payload(result, o), indent=2), file=out)
        return

    rep = result.report
    print("", file=out)
    print(energy_table(rep), file=out)
    print(verdict_block(result, rep), file=out)
    print(artifact_block(result, o), file=out)


def json_payload(result, o):
    rep = result.report
    warnings = sum(1 for e in (result.audit.entries if result.audit else [])
                   if e.get("level") == "warning")
    return {"compliant": result.compliant, "annual": rep.get("annual"),
            "determination": determination(result, rep),
            "vintage": rep.get("vintage"), "hdd": rep.get("hdd"),
            "tier": rep.get("tier"),
            "percent_of_target": rep.get("percent_of_target"),
            "proposed": slice_energy(rep.get("proposed")),
            "reference": slice_energy(rep.get("reference")),
            "run_dir": result.run_dir,
            "report_html": (os.path.join(result.run_dir,
                                         "compliance_report.html")
                            if o.get("report_html") else None),
            "warnings": warnings}


def slice_energy(section):
    if not section:
        return {}

    keys = ("total_site_kwh", "eui_kwh_per_m2", "floor_area_m2",
            "unmet_occupied_hours", "clean_run")
    return {k: section[k] for k in keys if k in section}


def energy_table(rep):
    """ASCII only, deliberately: the Windows console is CP437/CP1252 and this
    tool must not be the thing that breaks. 'kWh/m2', never a superscript."""
    p_sec = rep.get("proposed") or {}
    r_sec = rep.get("reference") or {}
    rule = "-" * 66
    lines = [rule,
             "%-12s %14s %14s %12s" % ("", "site kWh", "kWh/m2/yr", "area m2"),
             row("Proposed", p_sec)]
    if r_sec:
        lines.append(row("Reference", r_sec))
    margin = margin_line(p_sec, r_sec, rep)
    if margin is not None:
        lines.append(margin)
    unmet = unmet_line(p_sec, r_sec)
    if unmet is not None:
        lines.append(unmet)
    lines.append(rule)
    return "\n".join(lines)


def row(label, sec):
    return "%-12s %14s %14s %12s" % (
        label, num(sec.get("total_site_kwh")), num(sec.get("eui_kwh_per_m2")),
        num(sec.get("floor_area_m2")))


def margin_line(p_sec, r_sec, rep):
    """8.4.1.2.(2) is decided on TOTAL SITE ENERGY, not EUI — the pipeline
    compares total_site_kwh. Both are printed above, but the margin (the
    number the verdict rests on) must be the one the code test actually
    used."""
    pk = p_sec.get("total_site_kwh")
    rk = r_sec.get("total_site_kwh")
    if pk is None or rk is None or rk <= 0:
        return None

    pct = ruby_round(100.0 * (rk - pk) / rk, 1)
    tier = f"   Tier {rep['tier']}" if rep.get("tier") else ""
    verdict = (f"{ruby_str(pct)}% under target" if pct >= 0
               else f"{ruby_str(abs(pct))}% OVER target")
    return "%-12s %14s   %s%s" % ("Margin", num(ruby_round(rk - pk, 1)),
                                  verdict, tier)


def unmet_line(p_sec, r_sec):
    ph = (p_sec.get("unmet_occupied_hours") or {}).get("heating")
    if ph is None:
        return None

    r_unmet = r_sec.get("unmet_occupied_hours") or {}
    p_unmet = p_sec.get("unmet_occupied_hours") or {}
    return "%-12s heating %s / %s h    cooling %s / %s h" % (
        "Unmet hours", num(ph), num(r_unmet.get("heating")),
        num(p_unmet.get("cooling")), num(r_unmet.get("cooling")))


def determination(result, rep):
    if rep.get("annual") is False:
        return "NO DETERMINATION - run period shortened"
    if result.compliant is None:
        return "NO DETERMINATION - no annual simulation"

    return "COMPLIANT" if result.compliant else "NOT COMPLIANT"


def verdict_block(result, rep):
    rule = "-" * 66
    if rep.get("annual") is False:
        return "\n".join([
            "", "  *** NOT A CODE-COMPLIANT DETERMINATION ***",
            "  The run period was shortened (--quick). 8.4.1.2 requires a "
            "simulated",
            "  year. The comparison above is arithmetic only.", "",
            "  VERDICT: NO DETERMINATION", rule])
    if result.compliant is None:
        return "\n".join([
            "", f"  VERDICT: NO DETERMINATION (simulate: {rep.get('simulate')})",
            "  Run with --simulate annual for an 8.4.1.2 determination.", rule])
    verdict = "COMPLIANT" if result.compliant else "NOT COMPLIANT"
    return "\n".join([
        "", f"  VERDICT: {verdict}   (NECB {rep.get('vintage')}, Division B, "
            "Article 8.4.1.2)", rule])


def artifact_block(result, o):
    dir = result.run_dir
    lines = [""]
    if o.get("report_html"):
        lines.append(f"  Report   {os.path.join(dir, 'compliance_report.html')}")
    lines.append(f"  Audit    {os.path.join(dir, 'audit.txt')}")
    lines.append(f"  Data     {os.path.join(dir, 'report.json')}")
    warns = sum(1 for e in (result.audit.entries if result.audit else [])
                if e.get("level") == "warning")
    if warns > 0:
        lines.append(f"  {warns} warning(s) recorded - see audit.txt")
    return "\n".join(lines)


def preflight_help(err_obj, o, err):
    print("", file=err)
    print("ERROR: the model was REJECTED before any simulation ran.", file=err)
    print("", file=err)
    print(str(err_obj), file=err)  # already carries per-type did-you-mean hints
    if not (o.get("space_type") or o.get("space_type_map")):
        print("", file=err)
        print("Fix: tag each space type with standardsBuildingType + "
              "standardsSpaceType", file=err)
        print("from the NECB catalog, or re-run with the on-ramp, e.g.",
              file=err)
        print('  --space-type "Space Function/Office enclosed > 25 m2"',
              file=err)
    note = audit_note(o.get("run_dir"))
    if note:
        print(note, file=err)


def audit_note(run_dir):
    """The pipeline runs its failure flush before re-raising, so an audit
    trail exists even for a crash. Saying so turns a dead end into a next
    step."""
    if not (run_dir and os.path.exists(os.path.join(str(run_dir),
                                                    "audit.txt"))):
        return ""

    return ("\nA partial audit trail was written to "
            f"{os.path.join(run_dir, 'audit.txt')}")


def num(v):
    if v is None:
        return "-"
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return str(v)

    rounded = ruby_round(v)
    digits = str(abs(rounded))
    grouped = ",".join(reversed(
        [digits[::-1][i:i + 3][::-1] for i in range(0, len(digits), 3)]))
    whole = ("-" if rounded < 0 else "") + grouped
    if isinstance(v, float) and abs(v) < 1000:
        return ruby_str(ruby_round(v, 1))
    return whole


class Weather:
    """Weather resolution for --city.

    A demo that needs the network is a bad demo, so bundled files win and the
    download is only the long tail. Both the .ddy and the .stat must land
    BESIDE the .epw: attach_weather needs the design days, and the climate
    resolver reads the .stat next to the EPW before falling back to Table
    C-1."""

    @staticmethod
    def search():
        """Where to look for bundled weather, most authoritative first.
        BTAP_HOME is what a launcher actually sets; the checkout paths serve
        development (an installed wheel bundles no weather)."""
        python_root = Path(__file__).resolve().parents[2]
        candidates = []
        home = os.environ.get("BTAP_HOME") or os.environ.get("NECB_HOME")
        if home:
            candidates.append(os.path.join(home, "weather"))
        candidates.append(str(python_root / "tests" / "fixtures" / "weather"))
        return candidates

    @staticmethod
    def dirs():
        return [d for d in Weather.search() if os.path.isdir(d)]

    @staticmethod
    def available():
        """Earlier directories win: BTAP_HOME must not be shadowed by a
        checkout path that happens to exist."""
        found = {}
        for d in reversed(Weather.dirs()):
            for f in sorted(_glob.glob(os.path.join(d, "*.epw"))):
                found[Weather.city_of(f)] = f
        return found

    @staticmethod
    def city_of(path):
        """'CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw' -> 'toronto'"""
        parts = os.path.basename(path).split("_")
        third = parts[2] if len(parts) > 2 else ""
        return third.split(".")[0].lower()

    @staticmethod
    def catalogue_text():
        found = Weather.available()
        if not found:
            return "No weather files found in this installation."

        lines = ["Weather files available to --city:"]
        for city, path in sorted(found.items()):
            lines.append("  %-14s %s" % (city, os.path.basename(path)))
        return "\n".join(lines)

    @staticmethod
    def resolve(o):
        """:return: an error message, or None on success"""
        if not o.get("city"):
            return None
        if o.get("epw"):
            return "--city and --epw are mutually exclusive"

        available = Weather.available()
        match = available.get(o["city"].lower())
        if not match:
            return (f"unknown city: {o['city']}\n       "
                    f"known: {', '.join(sorted(available))}\n       "
                    "or pass --epw with an explicit path")

        o["epw"] = match
        return None


class Progress:
    """The pipeline has no callback hook and a real run is 40-90 minutes, so
    a silent terminal reads as a hang. Watch the run dir for the phase
    directories appearing instead — no API change, and it is what makes the
    demo watchable.

    Port note: the ticker is a daemon thread with a cooperative stop Event —
    Ruby's ``Thread#kill`` has no Python equivalent, and Ruby stops it in six
    places, so ``stop`` must be just as callable from every one of them
    (``run`` calls it on every path, and it is None-safe)."""

    PHASES = (("proposed_sizing", "proposed sizing run"),
              ("proposed_annual", "proposed annual run"),
              ("reference_sizing", "reference sizing run"),
              ("reference_annual", "reference annual run"))

    @staticmethod
    def start(run_dir, out):
        stop_event = threading.Event()
        seen = {}
        started = time.monotonic()

        def watch():
            while not stop_event.is_set():
                for dir_name, label in Progress.PHASES:
                    if seen.get(dir_name):
                        continue
                    if not os.path.isdir(os.path.join(str(run_dir), dir_name)):
                        continue

                    seen[dir_name] = True
                    print("  [%s] %-28s started"
                          % (Progress.stamp(started), label), file=out)
                stop_event.wait(2)

        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
        return (thread, stop_event)

    @staticmethod
    def stop(ticker):
        if ticker is None:
            return

        thread, stop_event = ticker
        stop_event.set()
        thread.join(timeout=5)

    @staticmethod
    def stamp(started):
        secs = round(time.monotonic() - started)
        return "%02d:%02d" % (secs // 60, secs % 60)


def main():
    """Console-script entry point. ``os._exit`` mirrors the Ruby shim's
    ``exit!``: set the status without unwinding — but it skips atexit and
    does NOT flush, so flush first."""
    code = run(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
