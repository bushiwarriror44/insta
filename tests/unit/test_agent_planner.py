import pytest
from pydantic import ValidationError

from app.agent.planner import (
    SYSTEM_PROMPT,
    ContentIdea,
    PlanRequest,
    build_prompt,
)


def idea(n: int = 1) -> ContentIdea:
    return ContentIdea(
        shots=[f"a misty pine ridge at dawn, slow drone push, shot {n}"],
        title=f"Ridge at dawn {n}",
        description="Fog moving through pines.",
        tags=["nature", "calm"],
    )


# --- prompt building ------------------------------------------------


def test_the_brief_and_count_reach_the_prompt():
    prompt = build_prompt(PlanRequest(brief="calm nature, misty forests", count=4))

    assert "calm nature, misty forests" in prompt
    assert "exactly 4 ideas" in prompt


def test_recent_titles_are_listed_so_the_agent_does_not_repeat_itself():
    prompt = build_prompt(
        PlanRequest(brief="b", count=2, recent_titles=["Morning ridge", "Rain"])
    )

    assert "do not repeat" in prompt
    assert "- Morning ridge" in prompt
    assert "- Rain" in prompt


def test_a_channel_with_no_history_gets_no_repeat_section():
    prompt = build_prompt(PlanRequest(brief="b", count=2))

    assert "do not repeat" not in prompt


def test_the_recent_list_is_capped():
    prompt = build_prompt(
        PlanRequest(brief="b", count=1, recent_titles=[f"t{i}" for i in range(200)])
    )

    assert prompt.count("\n- ") <= 25


def test_platform_and_length_are_stated():
    prompt = build_prompt(
        PlanRequest(brief="b", count=1, platform="tiktok", duration_s=10)
    )

    assert "Platform: tiktok" in prompt
    assert "10 seconds" in prompt


# --- configuration --------------------------------------------------


# --- planning -------------------------------------------------------


# --- error translation ----------------------------------------------


# --- schema ---------------------------------------------------------


#: A shot the schema is happy with, so each test below fails for the one
#: reason it is about.
GOOD_SHOT = "a misty pine ridge at dawn, slow drone push"


def test_a_shot_too_short_to_be_a_prompt_is_refused():
    with pytest.raises(ValidationError, match="not a shot description"):
        ContentIdea(shots=["short"], title="ok title")


def test_a_post_with_no_shots_is_refused():
    with pytest.raises(ValidationError, match="at least 1 item"):
        ContentIdea(shots=[], title="ok title")


def test_a_title_too_short_to_say_anything_is_refused():
    with pytest.raises(ValidationError, match="at least 3 characters"):
        ContentIdea(shots=[GOOD_SHOT], title="x")


def test_a_title_longer_than_any_platform_takes_is_refused():
    with pytest.raises(ValidationError, match="at most 100 characters"):
        ContentIdea(shots=[GOOD_SHOT], title="t" * 200)


def test_a_post_can_be_several_shots():
    idea = ContentIdea(
        shots=[
            "a wide shot of a misty pine ridge at dawn",
            "the same ridge, closer, fog moving through the branches",
        ],
        title="Ridge at dawn",
    )

    assert len(idea.shots) == 2


def test_padding_a_model_added_is_dropped_rather_than_rendered():
    # Asked for one to four, a small model returns four with two blank.
    idea = ContentIdea(
        shots=["a misty pine ridge at dawn", "  ", "", "fog through the branches"],
        title="Ridge at dawn",
    )

    assert idea.shots == ["a misty pine ridge at dawn", "fog through the branches"]


def test_more_shots_than_a_post_can_hold_are_trimmed():
    idea = ContentIdea(
        shots=[f"a misty pine ridge at dawn, take {n}" for n in range(9)],
        title="Ridge at dawn",
    )

    assert len(idea.shots) == 4


# --- tags are made usable rather than trusted ---------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("blue_hour", "bluehour"),
        ("blue hour", "bluehour"),
        ("#calm", "calm"),
        ("Calm", "calm"),
        ("slow-motion", "slowmotion"),
        ("dawn!!", "dawn"),
    ],
)
def test_a_tag_becomes_one_lowercase_token(raw, expected):
    # The prompt asks for this and a small model still returns blue_hour;
    # "blue hour" would break in half as a hashtag on Instagram.
    idea = ContentIdea(shots=["a misty ridge at dawn"], title="Ridge", tags=[raw])

    assert idea.tags == [expected]


def test_duplicate_tags_are_dropped():
    idea = ContentIdea(
        shots=["a misty ridge at dawn"],
        title="Ridge",
        tags=["blue_hour", "blue hour", "BlueHour"],
    )

    assert idea.tags == ["bluehour"]


def test_tags_that_normalise_to_nothing_are_dropped():
    idea = ContentIdea(
        shots=["a misty ridge at dawn"], title="Ridge", tags=["", "!!!", "###"]
    )

    assert idea.tags == []


def test_the_order_the_model_chose_is_kept():
    idea = ContentIdea(
        shots=["a misty ridge at dawn"],
        title="Ridge",
        tags=["fog", "ridge", "dawn"],
    )

    assert idea.tags == ["fog", "ridge", "dawn"]


# --- what the run log needs from a call ---------------------------------


# --- questions about the brief ------------------------------------------


def test_the_system_prompt_forbids_withholding_the_plan():
    # A model that stops and waits for an answer is worse than no agent.
    assert "never instead of it" in SYSTEM_PROMPT
    assert "Report the decision, do not wait on it." in SYSTEM_PROMPT


def test_the_system_prompt_asks_for_a_question_not_a_label():
    # qwen3:8b answered "audience interest" until this was spelled out.
    assert "A label is not a question." in SYSTEM_PROMPT
