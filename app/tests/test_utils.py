from app.utils import cleanup_job_suffix


def test_cleanup_job_suffix_accents():
    input_with_accent_character = "The Panty Piñata Polarization HDTV-1080p"
    expected_result = "thepantypiatapolarizationhdtv1080p"
    result = cleanup_job_suffix(input_with_accent_character)
    assert result == expected_result


def test_cleanup_job_suffix_accents_2():
    input_with_accent_character = "The Man in the High Castle - S03E03 - Sensō Kōi WEBDL-1080p Proper REAL"
    expected_result = "themaninthehighcastles03e03senskiwebdl1080pproperreal"
    result = cleanup_job_suffix(input_with_accent_character)
    assert result == expected_result


def test_cleanup_job_suffix_period():
    input_with_period_character = "The.Panty.Piata.Polarization.HDTV-1080p"
    expected_result = "thepantypiatapolarizationhdtv1080p"
    result = cleanup_job_suffix(input_with_period_character)
    assert result == expected_result


def test_cleanup_job_suffix_underscore():
    input_with_bad_character = "The_Panty_Piata_Polarization_HDTV-1080p"
    expected_result = "thepantypiatapolarizationhdtv1080p"
    result = cleanup_job_suffix(input_with_bad_character)
    assert result == expected_result
