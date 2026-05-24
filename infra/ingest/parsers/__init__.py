"""Format-aware parser dispatcher."""
from __future__ import annotations
from pathlib import Path


RAW_NGS_REJECT = {".fastq", ".fq", ".bam", ".cram", ".bcf"}


def parse_file(path: Path) -> str | None:
    """
    Parse a file to plain text for chunking + embedding.
    Returns None if the format is rejected (raw NGS files).
    Raises ValueError for unsupported extensions.
    """
    ext = path.suffix.lower()

    if ext in RAW_NGS_REJECT or (path.name.endswith(".fastq.gz") or path.name.endswith(".fq.gz")):
        raise ValueError(
            f"Raw NGS file rejected: {path.name}. "
            "Generate a QC report (FastQC/MultiQC) and ingest that instead."
        )

    if ext == ".pdf":
        from .pdf import parse_pdf
        return parse_pdf(path)

    if ext in (".docx",):
        from .office import parse_docx
        return parse_docx(path)

    if ext in (".xlsx", ".xls"):
        from .office import parse_excel
        return parse_excel(path)

    if ext in (".fasta", ".fa", ".fna", ".ffn", ".faa"):
        from .omics import parse_fasta
        return parse_fasta(path)

    if ext == ".vcf":
        from .omics import parse_vcf
        return parse_vcf(path)

    if ext in (".bed", ".wig", ".gtf", ".gff", ".gff3"):
        from .omics import parse_annotation
        return parse_annotation(path)

    if ext in (".txt", ".md", ".csv", ".tsv", ".json", ".html", ".htm"):
        from .text import parse_text
        return parse_text(path)

    raise ValueError(f"Unsupported format: {ext}")
