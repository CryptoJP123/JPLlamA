from dataclasses import dataclass

from typing import Dict

@dataclass

class Plan:

    intent: str

    route: str

    reasoning: bool = False

    presentation: bool = False

    obsidian: bool = False

class Planner:

    PRESENTATION_WORDS = (

        "presentation",

        "slides",

        "deck",

        "powerpoint",

        "ppt",

        "presenton",

    )

    REASONING_WORDS = (

        "analyse",

        "analyze",

        "why",

        "compare",

        "recommend",

        "decision",

    )

    OBSIDIAN_WORDS = (

        "obsidian",

        "opsx",

        "vault",

        "notes",

    )

    def plan(self, prompt: str) -> Plan:

        text = prompt.lower()

        presentation = any(w in text for w in self.PRESENTATION_WORDS)

        reasoning = any(w in text for w in self.REASONING_WORDS)

        obsidian = any(w in text for w in self.OBSIDIAN_WORDS)

        if presentation:

            return Plan(

                intent="presentation_build",

                route="presentation",

                reasoning=reasoning,

                presentation=True,

                obsidian=obsidian,

            )

        return Plan(

            intent="general",

            route="chat",

            reasoning=reasoning,

            presentation=False,

            obsidian=obsidian,

        )