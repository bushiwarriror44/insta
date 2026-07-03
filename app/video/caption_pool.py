"""Caption renderer with per-account variation, profiles and locale awareness.

Identical captions across accounts are a strong automation signal. We render
captions from templates with placeholders and rotating emoji + hashtag pools,
**organised by topical profile** (``nature``, ``lifestyle``, ``fitness``,
``food``, ``travel``) and **locale** (``en``/``ru`` to start, fall back to
``en``).

Hashtags are split into popularity *tiers* — ``viral``, ``medium``, ``niche``,
``longtail`` — and the renderer mixes them in a realistic ratio
(approximately ``2 viral + 4 medium + 3 niche + 1 longtail``). Hammering
``#viral`` or ``#fyp``-only hashtags is a textbook spam signal; mixing tiers
mirrors how organic creators actually tag their posts.

Template language is tiny on purpose:
    {emoji}      - one random emoji from the profile/emoji pool
    {emojis:N}   - N random emojis joined together
    {hashtags:K} - K hashtags from the supplied pool (legacy single-pool path)
    {tags}       - tier-mixed hashtag block (recommended for new templates)
    {newline}    - a literal '\\n'
    {body}       - one rendered body phrase
"""
from __future__ import annotations

import hashlib
import random
import re
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Locale resolution.
# ---------------------------------------------------------------------------

_TZ_TO_LOCALE: dict[str, str] = {
    "Europe/Moscow": "ru",
    "Europe/Kiev": "ru",
    "Europe/Kyiv": "ru",
    "Europe/Minsk": "ru",
    "Asia/Almaty": "ru",
    "Asia/Tashkent": "ru",
    "Asia/Yekaterinburg": "ru",
    "Asia/Tbilisi": "ru",
    # Default for everything else: English.
}


def resolve_locale(timezone: Optional[str]) -> str:
    """Map an account's IANA timezone to a caption locale (``en``/``ru``)."""
    if not timezone:
        return "en"
    return _TZ_TO_LOCALE.get(timezone, "en")


# ---------------------------------------------------------------------------
# Profile data: bodies + emoji + hashtag tiers, per profile + locale.
# ---------------------------------------------------------------------------


@dataclass
class ProfileSpec:
    bodies: dict[str, list[str]]  # locale -> body phrases
    emoji_pool: list[str]
    hashtag_tiers: dict[str, list[str]] = field(default_factory=dict)


CAPTION_PROFILES: dict[str, ProfileSpec] = {
    "nature": ProfileSpec(
        bodies={
            "en": [
                "Saving this little moment.",
                "Slow afternoon energy.",
                "Found peace in the small things.",
                "A breath of fresh air.",
                "Soft light, soft mind.",
                "Tiny escape from the noise.",
                "Letting the day move slow.",
                "Sound on for the full vibe.",
                "Catch the calm.",
                "Easy moments only.",
                "Quiet places, loud feelings.",
                "Just one more golden minute.",
                "Forest therapy session.",
                "Slow walk, full heart.",
                "Nature always wins.",
                "Rooted, grounded, breathing.",
                "Wind doing all the work today.",
                "Stillness is a flex.",
                "Trees don't rush, neither will I.",
                "Pocket of peace.",
            ],
            "ru": [
                "Сохраняю этот момент.",
                "Тихий день — лучший день.",
                "Природа лечит всё.",
                "Глоток свежего воздуха.",
                "Мягкий свет, мягкие мысли.",
                "Маленький побег от шума.",
                "Пусть день идёт неспешно.",
                "Звук обязателен.",
                "Поймал спокойствие.",
                "Только лёгкие моменты.",
                "Тихие места, громкие чувства.",
                "Ещё одна золотая минута.",
                "Лес — лучшая терапия.",
                "Медленный шаг, полное сердце.",
                "Природа всегда побеждает.",
            ],
        },
        emoji_pool=[
            "🌿", "🍃", "🌳", "🌲", "🌴", "🍀", "🌅", "🌄", "🌌", "🌙",
            "☀️", "🌊", "🌸", "🌺", "🌻", "🍂", "🪐", "🐾", "🐚", "🦋",
        ],
        hashtag_tiers={
            "viral": [
                "#nature", "#travel", "#explore", "#aesthetic", "#vibes",
                "#peaceful", "#beautifulworld", "#calm",
            ],
            "medium": [
                "#naturephotography", "#wanderlust", "#scenery", "#mindfulness",
                "#earthfocus", "#getoutside", "#stayandwander", "#liveauthentic",
                "#exploringtheglobe", "#planetearth",
            ],
            "niche": [
                "#slowliving", "#earthpix", "#wildernessculture", "#forestbathing",
                "#quietmoments", "#naturelovers_gr", "#splendid_earth",
                "#allnatureshots", "#ourplanetdaily", "#wonderfulnature",
            ],
            "longtail": [
                "#goldenhourwalks", "#calmnaturevibes", "#stillscenes",
                "#peacefulearthmoments", "#letthecountryside",
            ],
        },
    ),
    "lifestyle": ProfileSpec(
        bodies={
            "en": [
                "Soft mornings, soft mood.",
                "Slow days are productive too.",
                "Romanticising the small stuff.",
                "Coffee. Quiet. Repeat.",
                "Living for the in-betweens.",
                "Choosing comfort today.",
                "Little ritual, big difference.",
                "Doing less, feeling more.",
                "Sunday energy on a Tuesday.",
                "Cozy season, every season.",
                "Permission to take it slow.",
                "Energy match: gentle.",
                "Notice the nice things.",
                "Today, just be.",
                "Glow from the inside out.",
            ],
            "ru": [
                "Мягкое утро — мягкий настрой.",
                "Медленные дни тоже продуктивны.",
                "Учусь замечать мелочи.",
                "Кофе. Тишина. Повторить.",
                "Живу ради пауз между делами.",
                "Сегодня выбираю уют.",
                "Маленький ритуал — большая разница.",
                "Делать меньше, чувствовать больше.",
                "Воскресная энергия во вторник.",
                "Уютный сезон — круглый год.",
                "Разрешаю себе не спешить.",
            ],
        },
        emoji_pool=[
            "✨", "☕", "🤍", "🕯️", "📓", "🌷", "🍵", "🪞", "🧘", "🎧",
            "📷", "🌸", "💫", "🌼", "🌟", "🤎", "🍂", "🧺",
        ],
        hashtag_tiers={
            "viral": [
                "#lifestyle", "#aesthetic", "#vibes", "#mood", "#cozy",
                "#dailyinspo", "#instagood",
            ],
            "medium": [
                "#slowliving", "#mindfulliving", "#everydaymoments",
                "#cozyaesthetic", "#romanticizeyourlife", "#dailyinspiration",
                "#aestheticfeed", "#simplethings", "#wellbeingjourney",
            ],
            "niche": [
                "#myslowliving", "#cozyminimalism", "#calmlifestyle",
                "#aestheticlifestyle", "#smallmomentsofcalm",
                "#tinyjoysofeveryday", "#stillmood",
            ],
            "longtail": [
                "#cozysundayfeels", "#softlivingroutine", "#gentledailylife",
                "#thequietestmornings",
            ],
        },
    ),
    "fitness": ProfileSpec(
        bodies={
            "en": [
                "Showed up. That's the win.",
                "Discipline > motivation.",
                "Earned this sweat.",
                "Reps don't lie.",
                "One more set. Always.",
                "Stronger than yesterday.",
                "Trust the process.",
                "Body grateful, mind clear.",
                "Move daily, feel weekly.",
                "Tough sessions build calm minds.",
                "Slow gains, real gains.",
                "Patience is a muscle.",
            ],
            "ru": [
                "Пришёл — уже выиграл.",
                "Дисциплина > мотивация.",
                "Этот пот заслужен.",
                "Повторы не врут.",
                "Ещё один подход. Всегда.",
                "Сильнее, чем вчера.",
                "Доверяй процессу.",
                "Тело благодарит, голова ясная.",
            ],
        },
        emoji_pool=[
            "🔥", "💪", "🏋️", "🏃", "⚡", "🥇", "🧠", "🩵", "🦾", "🧘",
        ],
        hashtag_tiers={
            "viral": [
                "#fitness", "#workout", "#gym", "#training", "#motivation",
                "#fitlife",
            ],
            "medium": [
                "#fitnessjourney", "#strengthtraining", "#gymmotivation",
                "#fitfam", "#functionaltraining", "#dailymovement",
                "#progressnotperfection",
            ],
            "niche": [
                "#mindfulmovement", "#disciplineoverhype", "#sustainablefitness",
                "#trainsmartnotlong", "#consistencyiskey",
                "#slowprogressisstillprogress",
            ],
            "longtail": [
                "#earlymorninggymvibes", "#quietworkoutmood",
                "#discipline_over_motivation_daily",
            ],
        },
    ),
    "food": ProfileSpec(
        bodies={
            "en": [
                "Made this in 10 minutes. Wins.",
                "Bowl-shaped happiness.",
                "Tag someone who needs this recipe.",
                "Comfort food era.",
                "Easy weekday plate.",
                "Plate it like you mean it.",
                "Full belly, full heart.",
                "Recipe in the comments.",
                "This > takeout, every time.",
                "Saving this for later, you should too.",
            ],
            "ru": [
                "Сделал за 10 минут. Топ.",
                "Счастье в форме миски.",
                "Отметь того, кому нужен этот рецепт.",
                "Эпоха comfort food.",
                "Простая будничная тарелка.",
                "Сытный животик — счастливое сердце.",
                "Рецепт в комментариях.",
                "Это лучше любой доставки.",
            ],
        },
        emoji_pool=[
            "🍝", "🥗", "🍳", "🍜", "🥑", "🍑", "🍓", "🥐", "☕", "🍰",
            "🌶️", "🧄", "🍋",
        ],
        hashtag_tiers={
            "viral": [
                "#food", "#recipe", "#foodie", "#delicious", "#easyrecipes",
                "#instafood", "#yum",
            ],
            "medium": [
                "#homecooking", "#weeknightdinner", "#feedfeed", "#eatwell",
                "#mealprep", "#tastemademedoit", "#cookingathome",
                "#easydinnerideas",
            ],
            "niche": [
                "#weeknightcooking", "#thequickrecipe", "#fastpantrymeals",
                "#nourishingbowls", "#smallbatchrecipes",
                "#realsimplecooking",
            ],
            "longtail": [
                "#10minutedinneridea", "#quietkitchenmoments",
                "#cozypastanightathome",
            ],
        },
    ),
    "travel": ProfileSpec(
        bodies={
            "en": [
                "Pin this for later.",
                "Take me back.",
                "One day, one city.",
                "Found a spot you'd love.",
                "View > description.",
                "Slow travel only.",
                "Wandered until the lights came on.",
                "Worth every step.",
                "This place hits different at sunrise.",
                "Save this for your next trip.",
            ],
            "ru": [
                "Сохрани на будущее.",
                "Хочу обратно.",
                "Один день, один город.",
                "Нашёл место, которое тебе понравится.",
                "Вид важнее описания.",
                "Только медленные путешествия.",
                "Гулял до самых фонарей.",
                "Стоило каждого шага.",
            ],
        },
        emoji_pool=[
            "✈️", "🌍", "🗺️", "🧳", "📍", "🏝️", "🏔️", "🌆", "🌇", "🌉",
            "🏞️", "🛶", "🚞",
        ],
        hashtag_tiers={
            "viral": [
                "#travel", "#wanderlust", "#explore", "#travelgram",
                "#vacation", "#adventure",
            ],
            "medium": [
                "#travelphotography", "#exploringtheglobe", "#hiddengems",
                "#travelcommunity", "#passionpassport", "#travelinspiration",
                "#beautifuldestinations", "#instatravel",
            ],
            "niche": [
                "#slowtravel", "#offthepathtravel", "#smalltownscenes",
                "#europebyvan", "#localtravelvibes", "#walkingexploration",
            ],
            "longtail": [
                "#sunsetwalkingmood", "#oldtownalleyways",
                "#thequietsideofthecity",
            ],
        },
    ),
}

DEFAULT_PROFILE = "nature"


# ---------------------------------------------------------------------------
# Legacy single-pool defaults (kept for backwards compatibility).
# ---------------------------------------------------------------------------

DEFAULT_EMOJI_POOL = CAPTION_PROFILES["nature"].emoji_pool
DEFAULT_HASHTAG_POOL = (
    CAPTION_PROFILES["nature"].hashtag_tiers["viral"]
    + CAPTION_PROFILES["nature"].hashtag_tiers["medium"]
    + CAPTION_PROFILES["nature"].hashtag_tiers["niche"]
    + CAPTION_PROFILES["nature"].hashtag_tiers["longtail"]
)

DEFAULT_TEMPLATES = [
    "{emoji} {body} {emoji}{newline}{newline}{tags}",
    "{body}{newline}{newline}{emojis:2} {tags}",
    "{emojis:2} {body}{newline}{tags}",
    "{body} {emoji}{newline}{newline}{tags}",
    "{body}{newline}{emoji}{newline}{tags}",
]

DEFAULT_BODIES = CAPTION_PROFILES["nature"].bodies["en"]


# Default tier mix per single rendered caption (counts must sum to a
# realistic-looking total — roughly 8–12 hashtags is normal for short Reels).
DEFAULT_TIER_MIX = {"viral": 2, "medium": 4, "niche": 3, "longtail": 1}


PLACEHOLDER_RE = re.compile(r"\{(?P<name>[a-z_]+)(?::(?P<arg>[0-9]+))?\}")
_RECENT_SIGNATURES: dict[str, list[tuple[datetime, str]]] = {}
_REPEAT_WINDOW = timedelta(days=3)


def _seeded_rng(seed_basis: str) -> random.Random:
    digest = hashlib.sha256(seed_basis.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _resolve_profile(profile_name: Optional[str]) -> ProfileSpec:
    if profile_name and profile_name in CAPTION_PROFILES:
        return CAPTION_PROFILES[profile_name]
    return CAPTION_PROFILES[DEFAULT_PROFILE]


def _bodies_for_locale(profile: ProfileSpec, locale: str) -> list[str]:
    if locale in profile.bodies:
        return profile.bodies[locale]
    return profile.bodies.get("en", DEFAULT_BODIES)


def _mix_tier_hashtags(
    profile: ProfileSpec,
    rng: random.Random,
    tier_mix: dict[str, int] | None = None,
) -> str:
    """Sample hashtags from each popularity tier and join them."""
    mix = tier_mix or DEFAULT_TIER_MIX
    chosen: list[str] = []
    for tier, count in mix.items():
        pool = profile.hashtag_tiers.get(tier, [])
        if not pool or count <= 0:
            continue
        chosen.extend(rng.sample(pool, k=min(count, len(pool))))
    rng.shuffle(chosen)
    return " ".join(chosen)


def render_caption(
    *,
    account_username: str,
    template: Optional[str] = None,
    body_pool: Optional[Iterable[str]] = None,
    emoji_pool: Optional[Iterable[str]] = None,
    hashtag_pool: Optional[Iterable[str]] = None,
    seed: Optional[str] = None,
    profile: Optional[str] = None,
    locale: Optional[str] = None,
    timezone: Optional[str] = None,
    anti_repeat: bool = False,
) -> str:
    """Render a caption.

    ``seed`` should typically include the source video name and timestamp so
    two posts in different runs differ even with the same template.

    ``profile`` selects a topical :class:`ProfileSpec` (``nature`` /
    ``lifestyle`` / ``fitness`` / ``food`` / ``travel``); ``locale`` selects
    the body phrases pool. If ``locale`` is omitted, ``timezone`` is used to
    infer one (e.g. ``Europe/Moscow`` → ``ru``); otherwise ``en``.

    For backwards compatibility, an explicit ``body_pool``/``emoji_pool``/
    ``hashtag_pool`` overrides the profile data.
    """
    rng = _seeded_rng(seed or f"{account_username}:{random.random()}")

    profile_spec = _resolve_profile(profile)
    effective_locale = locale or resolve_locale(timezone)

    bodies = list(body_pool) if body_pool else _bodies_for_locale(profile_spec, effective_locale)
    emojis = list(emoji_pool) if emoji_pool else profile_spec.emoji_pool
    legacy_hashtags = (
        list(hashtag_pool)
        if hashtag_pool
        else (
            profile_spec.hashtag_tiers.get("viral", [])
            + profile_spec.hashtag_tiers.get("medium", [])
            + profile_spec.hashtag_tiers.get("niche", [])
            + profile_spec.hashtag_tiers.get("longtail", [])
        )
    )

    template = template or rng.choice(DEFAULT_TEMPLATES)
    body = rng.choice(bodies)

    def replace(match: re.Match) -> str:
        name = match.group("name")
        arg = match.group("arg")
        if name == "emoji":
            return rng.choice(emojis)
        if name == "emojis":
            n = int(arg or 2)
            return "".join(rng.sample(emojis, k=min(n, len(emojis))))
        if name == "hashtags":
            n = int(arg or 5)
            return " ".join(rng.sample(legacy_hashtags, k=min(n, len(legacy_hashtags))))
        if name == "tags":
            # Only use tier mix when the profile has tiered data; otherwise
            # fall back to a flat sample.
            if profile_spec.hashtag_tiers:
                return _mix_tier_hashtags(profile_spec, rng)
            n = int(arg or 8)
            return " ".join(rng.sample(legacy_hashtags, k=min(n, len(legacy_hashtags))))
        if name == "newline":
            return "\n"
        if name == "body":
            return body
        return match.group(0)

    caption = PLACEHOLDER_RE.sub(replace, template).strip()
    if anti_repeat:
        caption = _anti_repeat_guard(caption, account_username=account_username, rng=rng)
    return caption


def _anti_repeat_guard(caption: str, *, account_username: str, rng: random.Random) -> str:
    tags = re.findall(r"#\w+", caption)
    if not tags:
        return caption
    signature = " ".join(sorted(set(t.lower() for t in tags)))
    now = datetime.now(timezone.utc)
    bucket = _RECENT_SIGNATURES.setdefault(account_username, [])
    bucket[:] = [(ts, sig) for ts, sig in bucket if now - ts <= _REPEAT_WINDOW]
    if signature in {sig for _, sig in bucket}:
        # Drop 1-2 hashtags to avoid exact repeats for this account in a short window.
        keep = max(1, len(tags) - rng.randint(1, min(2, len(tags))))
        kept_tags = tags[:keep]
        caption_wo_tags = re.sub(r"(?:#\w+\s*)+$", "", caption).strip()
        caption = f"{caption_wo_tags}\n\n{' '.join(kept_tags)}".strip()
        signature = " ".join(sorted(set(t.lower() for t in kept_tags)))
    bucket.append((now, signature))
    return caption
