"""Builds tests/fixtures/docs/public/cv_job_market.pdf. Run: python tests/make_test_pdf.py

General description of the computer vision job market for UK freshers. Test file only. It holds no
statistics on purpose, so nothing in it can be wrong or out of date.
"""

import textwrap
from pathlib import Path

from pdfmaker import make_pdf

PAGES = [
    (
        "Computer vision jobs for freshers in the UK: where the demand comes from",
        ("Computer vision engineers are hired wherever a camera replaces a human eye. "
         "In the UK, typical employers include makers of driver assistance and autonomous "
         "vehicle systems, factories that inspect products on a production line, retailers that "
         "count customers and track stock, health technology firms that read medical images, "
         "and drone and security companies that watch large sites. Graduate roles often carry "
         "titles such as graduate machine learning engineer, junior computer vision engineer "
         "or research assistant."),
    ),
    (
        "Skills UK employers ask for from new graduates",
        ("Job adverts for graduate computer vision roles usually ask for strong Python, "
         "experience with PyTorch or TensorFlow, and practical use of OpenCV. Employers like "
         "to see object detection and tracking work with models from the YOLO family. Teams "
         "that ship products also want deployment skills, such as exporting a model to ONNX, "
         "running it on a small device, and measuring its speed. Knowing how to evaluate a "
         "model honestly matters as much as training it. A degree in computer science, "
         "engineering, mathematics or a related field is the usual starting point, and a "
         "master's degree in AI is common among applicants."),
    ),
    (
        "How freshers stand out, and the right to work",
        ("Entry level roles attract many applicants, so evidence counts. A public project with "
         "a clear README, measured results and an honest list of limits shows more than a list "
         "of course certificates. Candidates who explain what failed, and how they tested it, "
         "are easier to trust. A short demo that a recruiter can run in minutes helps too. "
         "International graduates should check each advert for the right to work in the UK, "
         "because some employers cannot offer visa sponsorship and say so in the advert."),
    ),
]


def build(out):
    pages = [[title, ""] + textwrap.wrap(body, 80) for title, body in PAGES]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(make_pdf(pages))


if __name__ == "__main__":
    out = Path(__file__).parent / "fixtures" / "docs" / "public" / "cv_job_market.pdf"
    build(out)
    print(f"wrote {out}")
