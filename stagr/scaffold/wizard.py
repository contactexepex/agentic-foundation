"""Interactive `stagr init` wizard — collect config choices, then render via `generate`."""
from __future__ import annotations

from typing import Any, Callable

from ..render import DEFAULT_TOKEN_SECRET

from .detect import BUILD_PRESETS, CUSTOM_PRESET, _BUILD_PRESET_OPTIONS, detect_build_preset
from .defaults import (
    DEFAULT_BRANCH,
    DEFAULT_MODEL,
    DEFAULT_PLATFORM,
    PROFILES,
    _profile_security_blocking,
)


# --------------------------------------------------------------------------- interactive wizard


def _ask(read_input: Callable[[str], str], write_line: Callable[[str], None],
         prompt: str, default: str, options: str = "") -> str:
    """Ask one question, showing options and the default; empty input accepts the default."""
    options_suffix = f" [{options}]" if options else ""
    write_line(f"{prompt}{options_suffix}")
    answer = read_input(f"  > (default: {default}) ").strip()
    return answer or default


def run_wizard(read_input: Callable[[str], str] = input,
               write_line: Callable[[str], None] = print) -> dict[str, Any]:
    """Collect config choices interactively, grouped and defaulted. Returns a `choices` dict.

    IO is injected (`read_input`/`write_line`) so the flow is unit-testable. Every prompt offers a
    default (Enter accepts it), so a user can complete onboarding by pressing Enter throughout.
    """
    write_line("stagr init — let's set up .agentic/config.yml. Press Enter to accept each default.\n")

    write_line("── Scope ──")
    profile = _ask(read_input, write_line, "Profile (how many stages to scaffold)", "standard",
                   "minimal | standard | full | custom")
    if profile not in PROFILES:
        write_line(f"  (unknown profile '{profile}', using 'standard')")
        profile = "standard"

    write_line("\n── Platform ──")
    # Only GitHub renders today; other platforms are roadmap, so don't offer a choice that would
    # generate a config `doctor`/`apply` can't render.
    write_line(f"Platform: {DEFAULT_PLATFORM} (the only rendered platform today; others are roadmap).")
    platform = DEFAULT_PLATFORM
    default_branch = _ask(read_input, write_line, "Default branch", DEFAULT_BRANCH)

    write_line("\n── Model & secrets ──")
    model = _ask(read_input, write_line, "Claude implementer model id", DEFAULT_MODEL)
    token_secret = _ask(read_input, write_line, "Secret NAME for the remediation/publish PAT",
                        DEFAULT_TOKEN_SECRET)

    write_line('\n── Build ("green" checks) ──')
    # Propose the toolchain autodetected from the repo (markers in the CWD); the user can override it.
    detected_preset = detect_build_preset()
    build_preset = _ask(read_input, write_line, "Build preset", detected_preset, _BUILD_PRESET_OPTIONS)
    if build_preset not in BUILD_PRESETS:
        # The schema permits only the listed presets; a typo would generate a config that
        # immediately fails `stagr doctor`. Fall back to the toolchain-agnostic 'custom'.
        write_line(f"  (unknown preset '{build_preset}', using '{CUSTOM_PRESET}')")
        build_preset = CUSTOM_PRESET
    # A blank test command inherits the preset's test command at render time (render._build_steps
    # ignores an empty override), so say that rather than "fill later" when a preset is selected.
    test_prompt = ("Test command (blank uses the preset's default)" if build_preset != CUSTOM_PRESET
                   else "Test command (blank to set later)")
    build_test = _ask(read_input, write_line, test_prompt, "")

    security_blocking = _profile_security_blocking(profile)
    if profile in ("standard", "full"):
        write_line("\n── Governance ──")
        profile_default = "y" if security_blocking else "n"
        answer = _ask(read_input, write_line, "Make the security review blocking?",
                      profile_default, "y | n").strip().lower()
        if answer in ("y", "yes", "true"):
            security_blocking = True
        elif answer in ("n", "no", "false"):
            security_blocking = False
        else:
            # Don't let an unrecognized entry silently decide a security gate — keep the profile's
            # canonical default rather than defaulting an ambiguous answer to advisory.
            write_line(f"  (unrecognized '{answer}', keeping the profile default: "
                       f"{'blocking' if security_blocking else 'advisory'})")

    return {
        "profile": profile,
        "platform": platform,
        "default_branch": default_branch,
        "model": model,
        "token_secret": token_secret,
        "build_preset": build_preset,
        "build_test": build_test,
        "security_blocking": security_blocking,
    }
