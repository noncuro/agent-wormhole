from agent_wormhole.wordlist import generate_code, parse_code, WORDS


def test_wordlist_has_256_words():
    assert len(WORDS) == 256


def test_wordlist_words_are_lowercase_alpha():
    for word in WORDS:
        assert word.isalpha()
        assert word.islower()
        assert 3 <= len(word) <= 10


def test_generate_code_format():
    code = generate_code(port=9471)
    parts = code.split("-")
    assert len(parts) == 4
    assert parts[0] == "9471"
    assert parts[1] in WORDS
    assert parts[2] in WORDS
    assert parts[3] in WORDS


def test_generate_code_preserves_port():
    code = generate_code(port=12345)
    parts = code.split("-")
    assert parts[0] == "12345"


def test_parse_code_with_host():
    port, words, hostname = parse_code("9471-alpha-bravo-charlie@myhost")
    assert port == 9471
    assert words == "9471-alpha-bravo-charlie"
    assert hostname == "myhost"


def test_parse_code_without_host():
    port, words, hostname = parse_code("9471-alpha-bravo-charlie")
    assert port == 9471
    assert words == "9471-alpha-bravo-charlie"
    assert hostname is None


def test_parse_code_invalid_format():
    import pytest
    with pytest.raises(ValueError):
        parse_code("invalid")
    with pytest.raises(ValueError):
        parse_code("9471-alpha")
    with pytest.raises(ValueError):
        parse_code("9471-alpha-bravo")


def test_generate_codes_are_unique():
    codes = {generate_code(port=5555) for _ in range(50)}
    assert len(codes) > 1
