"""«Bimi пропонує» у боті: підказана категорія — перша кнопка, без дубля в списку."""
from keyboards.inline import generate_mono_keyboard

CATS = [{"id": i, "name": f"C{i}"} for i in range(1, 12)]


def test_suggested_category_first_and_not_duplicated():
    kb = generate_mono_keyboard(5, CATS, suggested={"category_id": 7}).inline_keyboard
    assert kb[0][0].text == "✨ C7" and kb[0][0].callback_data == "mcat:5:7" and len(kb[0]) == 1
    texts = [b.text for row in kb[1:] for b in row]
    assert "C7" not in texts and "C1" in texts


def test_no_or_unknown_suggestion_keeps_old_keyboard():
    assert generate_mono_keyboard(5, CATS).inline_keyboard == generate_mono_keyboard(5, CATS, suggested={}).inline_keyboard
    assert generate_mono_keyboard(5, CATS, suggested={"category_id": 99}).inline_keyboard[0][0].text == "C1"
