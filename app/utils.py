import re


def cleanup_job_suffix(input_string):
    # keep only word character, removing all non-word chars
    job_suffix = re.sub(r"\W", "", input_string.lower(), flags=re.I)
    job_suffix = re.sub(r"[à-ú]|[À-Ú]", "", job_suffix, flags=re.I)
    return job_suffix