"""House style rules, as a script rather than as a thing reviewers are asked to notice.

Every rule here exists because it is the kind of thing that gets waved through in review
when someone is tired, and then shows up in fifty lessons two months later.
"""

from .rules import ALL_RULES, Finding, check_file, check_text

__all__ = ["ALL_RULES", "Finding", "check_file", "check_text"]
