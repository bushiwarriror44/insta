from app.assistant.attachments import (
    attachment_operator_hint,
    messages_for_thread,
    user_content_with_attachments,
)


def test_user_content_with_attachments():
    text = user_content_with_attachments(
        {
            "role": "user",
            "content": "сделай ролик",
            "attachments": [
                {"filename": "ref.png", "media_type": "image", "role": "start_image"},
            ],
        }
    )
    assert "ref.png" in text
    assert "start_image" in text


def test_attachment_operator_hint_last_user_only():
    messages = [
        {"role": "user", "content": "hi", "attachments": [{"filename": "a.jpg"}]},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "again"},
    ]
    hint = attachment_operator_hint(messages)
    assert hint == ""

    messages[-1]["attachments"] = [{"filename": "b.webp", "media_type": "image"}]
    hint = attachment_operator_hint(messages)
    assert "b.webp" in hint
    assert "image_to_video" in hint


def test_messages_for_thread_includes_attachment_line():
    thread = messages_for_thread(
        [
            {
                "role": "user",
                "content": "go",
                "attachments": [{"filename": "x.png"}],
            }
        ]
    )
    assert thread == [{"role": "user", "content": "go\n[вложение: x.png, image, start_image]"}]
