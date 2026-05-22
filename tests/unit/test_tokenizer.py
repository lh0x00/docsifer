from docsifer.core.tokenizer import TiktokenCounter


def test_counts_zero_for_empty() -> None:
    assert TiktokenCounter("gpt-4o").count("") == 0


def test_counts_positive_for_text() -> None:
    counter = TiktokenCounter("gpt-4o")
    assert counter.count("Hello world!") > 0


def test_unknown_model_falls_back() -> None:
    # Should not raise; falls back to cl100k_base or whitespace.
    counter = TiktokenCounter("definitely-not-a-real-model")
    assert counter.count("hello world") > 0
