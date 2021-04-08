from string import ascii_letters, digits


def cleanup_job_suffix(input_string):
    # keep only a-z and 0-9
    job_suffix = "".join([ch for ch in input_string if ch in (ascii_letters + digits)])
    return job_suffix.lower()
