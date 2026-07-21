from core.research.sec_lexical_features import (
    compute_lexical_features,
    extract_visible_text,
)


def test_visible_text_excludes_script_style_and_hidden_xbrl():
    payload = b"""
    <html><head><title>hidden title</title></head><body>
      Strong growth and improved profit.
      <script>negative loss decline</script>
      <style>weakness { color: red }</style>
      <ix:hidden>uncertain litigation</ix:hidden>
    </body></html>
    """
    text = extract_visible_text(payload, "text/html")
    assert "Strong growth" in text
    assert "negative loss" not in text
    assert "uncertain litigation" not in text


def test_lexical_features_measure_tone_and_uncertainty():
    text = ("Strong growth improved profit opportunity. " * 20) + (
        "Risk may be uncertain and could decline. " * 10)
    features = compute_lexical_features(text)
    assert features["positive_per_1000"] > features["negative_per_1000"]
    assert features["uncertainty_per_1000"] > 0
    assert features["text_word_count_log1p"] > 0
