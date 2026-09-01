"""PredictionGate: ask before you show.

Rule 2 of the pedagogy is that a reader predicts before they look. It is the rule that does most
of the work and the easiest one to skip, because reading an answer is faster than committing to
one. This puts the answer behind a fold and the question in front of it.

    from kxwidgets import PredictionGate

    gate = PredictionGate(
        "How many kernel functions does writing one byte call?",
        options={"a": "about ten", "b": "about a hundred", "c": "about a thousand"},
        answer="b",
        why="A write to a file already in the page cache is around a hundred calls deep.",
    )
    gate                       # ask
    gate.check("a")            # commit, then find out

The answer is sitting in the notebook, so anybody can read it out of the file instead of guessing.
That is fine. This is a speed bump and not a lock. A prediction you wrote down and got wrong is a
thing you remember, and a lock would only teach people to resent the book.
"""

from __future__ import annotations

from dataclasses import dataclass

from kxwidgets.html import BAND, INK, LINE, MONO, MUTED, Widget, card, details, style, tag, text

LETTERS = "abcdefghijklmnopqrstuvwxyz"

RIGHT = "#d9edd2"
WRONG = "#f6d9dd"


def _as_options(options: dict[str, str] | list[str] | None) -> dict[str, str]:
    if options is None:
        return {}
    if isinstance(options, dict):
        return dict(options)
    return {LETTERS[index]: one for index, one in enumerate(options)}


@dataclass(frozen=True)
class Verdict(Widget):
    """What came back after a reader committed to an answer.

    Being wrong is not a failure state and is not drawn like one. The interesting cases in this
    book are almost all cases where the obvious answer is wrong, so the explanation is shown
    either way and the colour is the only thing that differs.
    """

    question: str
    chosen: str
    answer: str
    why: str
    correct: bool
    chosen_text: str = ""
    answer_text: str = ""

    def html(self) -> str:
        head = "That is right." if self.correct else "Not this one."
        lines = [
            tag("div", text(f"You said: {self.chosen_text or self.chosen}")),
            tag("div", text(f"The answer is: {self.answer_text or self.answer}")),
        ]
        body = tag(
            "div",
            tag("div", text(head), style_=style(font_weight="600", margin_bottom="4px"))
            + "".join(lines)
            + tag(
                "div",
                text(self.why),
                style_=style(margin_top="6px", color=MUTED, line_height="1.5"),
            ),
            style_=style(
                background=RIGHT if self.correct else WRONG,
                border=f"1px solid {LINE}",
                border_radius="4px",
                padding="10px 12px",
                font_size="13px",
                color=INK,
            ),
        )
        return card("Prediction", self.question, body, fallback=self.text())

    def text(self) -> str:
        head = "right" if self.correct else "not this one"
        return "\n".join(
            [
                self.question,
                f"you said:       {self.chosen_text or self.chosen}",
                f"the answer is:  {self.answer_text or self.answer}",
                f"verdict:        {head}",
                "",
                self.why,
            ]
        )


class PredictionGate(Widget):
    """One question, its options, and the answer folded away underneath.

    Works with options or without them. Without options it is a free text prompt, the check is a
    case insensitive string comparison, and it suits questions like naming the outermost function
    in a trace.
    """

    def __init__(
        self,
        question: str,
        *,
        answer: str,
        why: str,
        options: dict[str, str] | list[str] | None = None,
        reveal: str = "Show what actually happens",
    ) -> None:
        self.question = question
        self.options = _as_options(options)
        self.answer = answer
        self.why = why
        self.reveal = reveal
        if self.options and answer not in self.options:
            raise KeyError(f"the answer {answer!r} is not one of the options offered")

    def check(self, chosen: str) -> Verdict:
        """Grade one answer. Case and surrounding space do not count."""
        tidy = chosen.strip().lower()
        correct = tidy == self.answer.strip().lower()
        return Verdict(
            question=self.question,
            chosen=chosen,
            answer=self.answer,
            why=self.why,
            correct=correct,
            chosen_text=self.options.get(tidy, ""),
            answer_text=self.options.get(self.answer, ""),
        )

    def html(self) -> str:
        body = self._options() if self.options else self._free_text()
        answer = self.options.get(self.answer, self.answer)
        revealed = tag(
            "div",
            tag("div", text(f"The answer is {self.answer}: {answer}"))
            + tag(
                "div",
                text(self.why),
                style_=style(margin_top="6px", color=MUTED, line_height="1.5"),
            ),
            style_=style(
                background=BAND,
                border=f"1px solid {LINE}",
                border_radius="4px",
                padding="10px 12px",
                margin_top="6px",
                font_size="13px",
            ),
        )
        return card(
            "Predict first",
            self.question,
            body + details(text(self.reveal), revealed),
            "Write your answer down before you open this. A prediction you got wrong is a thing "
            "you remember, and a fact you read passively is not.",
            fallback=self.text(),
        )

    def _options(self) -> str:
        rows = []
        for key, value in self.options.items():
            label = tag(
                "span",
                text(key),
                style_=style(
                    font_family=MONO,
                    font_weight="600",
                    display="inline-block",
                    width="20px",
                    color=MUTED,
                ),
            )
            rows.append(
                tag(
                    "div",
                    label + text(value),
                    style_=style(padding="4px 0", font_size="13px"),
                )
            )
        return tag("div", "".join(rows), style_=style(margin_bottom="8px"))

    def _free_text(self) -> str:
        return tag(
            "div",
            "Say it out loud or write it in the next cell. There are no options on this one on "
            "purpose, because picking from a list is not the same as producing an answer.",
            style_=style(font_size="13px", color=MUTED, margin_bottom="8px"),
        )

    def text(self) -> str:
        lines = [self.question]
        for key, value in self.options.items():
            lines.append(f"  {key}  {value}")
        lines.append("")
        lines.append(f"answer: {self.answer}")
        lines.append(self.why)
        return "\n".join(lines)
