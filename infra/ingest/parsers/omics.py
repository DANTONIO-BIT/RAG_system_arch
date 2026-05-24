"""
Omics-format parsers for genomics/bioinformatics files.

RAW sequencing files (FASTQ, BAM, CRAM) are NEVER parsed here.
What IS embeddable:
  FASTA  — genes, proteins (short sequences + biological context)
  VCF    — annotated variants (functional annotations only)
  BED    — annotated genomic features
  WIG    — coverage/signal tracks (summary)
  GTF/GFF — gene annotations
"""
from __future__ import annotations
from pathlib import Path


def parse_fasta(path: Path) -> str:
    """Extract sequence IDs + descriptions. Does not embed raw nucleotide strings."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    headers: list[str] = []
    current_len = 0
    records: list[str] = []

    for line in lines:
        if line.startswith(">"):
            if headers:
                records.append(f"{headers[-1]} [length: {current_len} bp]")
            headers.append(line[1:].strip())
            current_len = 0
        else:
            current_len += len(line.strip())

    if headers:
        records.append(f"{headers[-1]} [length: {current_len} bp]")

    summary = (
        f"FASTA file: {path.name}\n"
        f"Total sequences: {len(records)}\n\n"
        + "\n".join(records[:200])  # cap at 200 sequences
    )
    if len(records) > 200:
        summary += f"\n... and {len(records) - 200} more sequences."
    return summary


def parse_vcf(path: Path) -> str:
    """Extract annotated variant records. Skips raw genotype columns."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_lines: list[str] = []
    variant_lines: list[str] = []

    for line in lines:
        if line.startswith("##"):
            # Keep INFO field descriptions
            if "INFO=<ID=" in line:
                header_lines.append(line.strip())
        elif line.startswith("#"):
            header_lines.append(line.strip())
        else:
            parts = line.split("\t")
            if len(parts) >= 8:
                # CHROM POS ID REF ALT QUAL FILTER INFO only
                variant_lines.append("\t".join(parts[:8]))

    summary = (
        f"VCF file: {path.name}\n"
        f"Variants: {len(variant_lines)}\n\n"
        "## INFO field definitions\n"
        + "\n".join(header_lines[:30]) + "\n\n"
        "## Variant records (CHROM POS ID REF ALT QUAL FILTER INFO)\n"
        + "\n".join(variant_lines[:500])
    )
    if len(variant_lines) > 500:
        summary += f"\n... and {len(variant_lines) - 500} more variants."
    return summary


def parse_annotation(path: Path) -> str:
    """Parse BED, WIG, GTF, GFF annotation files."""
    ext = path.suffix.lower()
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    non_comment = [l for l in lines if l.strip() and not l.startswith(("#", "track", "browser"))]

    if ext == ".wig":
        return (
            f"WIG coverage file: {path.name}\n"
            f"Data lines: {len(non_comment)}\n\n"
            + "\n".join(non_comment[:100])
        )

    if ext == ".bed":
        return (
            f"BED annotation file: {path.name}\n"
            f"Features: {len(non_comment)}\n\n"
            + "\n".join(non_comment[:300])
        )

    if ext in (".gtf", ".gff", ".gff3"):
        gene_lines = [l for l in non_comment if "\tgene\t" in l or "\tmRNA\t" in l]
        return (
            f"{'GTF' if ext == '.gtf' else 'GFF'} annotation: {path.name}\n"
            f"Total features: {len(non_comment)} | Gene/mRNA features: {len(gene_lines)}\n\n"
            + "\n".join(gene_lines[:300])
        )

    return "\n".join(non_comment[:500])
