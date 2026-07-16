"""
LaTeX Motivation Letter Generator Service
Generates PDF motivation letters from templates
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import subprocess
import os
import tempfile
import shutil

router = APIRouter(prefix="/api/latex", tags=["latex"])

class LetterData(BaseModel):
    sender_name: str
    sender_address: str
    sender_email: str
    sender_phone: str
    company_name: str
    company_address: str
    city: str
    job_title: str
    field: str
    date: str
    custom_text: Optional[str] = ""

LATEX_TEMPLATE = r"""
\documentclass[12pt,a4paper]{letter}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[ngerman]{babel}
\usepackage{geometry}
\geometry{left=2.5cm,right=2.5cm,top=2.5cm,bottom=2.5cm}

\begin{document}

\begin{letter}{
    {{COMPANY_NAME}}\\
    {{COMPANY_ADDRESS}}\\
    {{CITY}}
}

\opening{Sehr geehrte Damen und Herren,}

hiermit bewerbe ich mich um einen {{JOB_TITLE}} in Ihrem Hause in {{CITY}}.

{{CUSTOM_TEXT}}

Im Anhang finden Sie meine vollständigen Bewerbungsunterlagen, bestehend aus meinem Lebenslauf und meinen Zeugnissen.

Über eine Einladung zu einem persönlichen Gespräch würde ich mich sehr freuen.

\closing{Mit freundlichen Grüßen,}

\ps{}
{{SENDER_NAME}}

\end{letter}
\end{document}
"""

def generate_latex_content(data: LetterData) -> str:
    """Generate LaTeX content from template"""
    content = LATEX_TEMPLATE

    replacements = {
        "{{COMPANY_NAME}}": data.company_name,
        "{{COMPANY_ADDRESS}}": data.company_address or "",
        "{{CITY}}": data.city,
        "{{JOB_TITLE}}": data.job_title or "Ausbildungsplatz",
        "{{CUSTOM_TEXT}}": data.custom_text or "",
        "{{SENDER_NAME}}": data.sender_name,
    }

    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)

    return content

@router.post("/generate-letter")
async def generate_motivation_letter(data: LetterData):
    """Generate PDF motivation letter"""
    try:
        # Create temp directory
        temp_dir = tempfile.mkdtemp()
        tex_file = os.path.join(temp_dir, "motivation_letter.tex")

        # Generate LaTeX content
        latex_content = generate_latex_content(data)

        # Write to file
        with open(tex_file, "w", encoding="utf-8") as f:
            f.write(latex_content)

        # Compile with pdflatex
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-output-directory", temp_dir, tex_file],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            # Try again (sometimes needs 2 passes)
            result = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-output-directory", temp_dir, tex_file],
                capture_output=True,
                text=True,
                timeout=30
            )

        pdf_file = os.path.join(temp_dir, "motivation_letter.pdf")

        if not os.path.exists(pdf_file):
            raise HTTPException(status_code=500, detail="PDF generation failed")

        # Read PDF
        with open(pdf_file, "rb") as f:
            pdf_bytes = f.read()

        # Cleanup
        shutil.rmtree(temp_dir)

        return {
            "success": True,
            "filename": f"Bewerbung_{data.company_name.replace(' ', '_')}.pdf",
            "pdf_base64": pdf_bytes.hex(),
            "size": len(pdf_bytes)
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="LaTeX compilation timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

@router.post("/preview")
async def preview_latex(data: LetterData):
    """Preview LaTeX source (for debugging)"""
    return {
        "latex": generate_latex_content(data)
    }