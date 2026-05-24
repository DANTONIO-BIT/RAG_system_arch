#!/Library/Developer/CommandLineTools/usr/bin/python3
"""
save_feedback.py — Guarda feedback del evaluador en archivo local y Engram.

Uso:
  python3.9 save_feedback.py --topic TRANSF.DIGITAL --unit 5 --case "CP Hotel" \
    --note notable --date 2026-05-10 --feedback "Texto del feedback aquí"

  python3.9 save_feedback.py --topic Nexus_IA_Big_Data_turism --unit 4 \
    --case "CP Alhambra" --note notable --file /path/to/feedback.txt
"""
import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
INPUT_DIR = BASE_DIR / "input"

TOPIC_TO_FOLDER = {
    "TRANSF.DIGITAL": "TRANSF.DIGITAL",
    "Nexus_IA_Big_Data_turism": "Nexus_IA_Big_Data_turism",
    "Emprendimiento": "Emprendimiento",
    "Agente_inmobiliario": "Agente_inmobiliario",
    "web_developement": "web_developement",
}

FEEDBACK_TEMPLATE = """\
---
tipo: feedback_evaluador
curso: {topic}
unidad: {unit}
caso: {case}
fecha: {date}
nota: {note}
---

## Feedback del evaluador

{feedback_text}

## Qué funcionó bien

- [Completar tras análisis del feedback]

## Qué faltó (patrón de error)

- [Completar tras análisis del feedback]

## Regla aprendida

**[TÍTULO DE LA REGLA EN MAYÚSCULAS]**

❌ [Ejemplo de lo que se hizo mal]
✅ [Ejemplo de cómo debería ser]

## Aplica a

- {topic} — Unidad {unit}
"""


def slugify(text: str) -> str:
    return text.lower().replace(" ", "_").replace("/", "_")[:30]


def save_local(topic: str, unit: str, case: str, note: str,
               feedback_date: str, feedback_text: str) -> Path:
    folder = TOPIC_TO_FOLDER.get(topic, topic)
    feedback_dir = INPUT_DIR / folder / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)

    case_slug = slugify(case)
    filename = f"fb_unidad{unit}_{case_slug}_{feedback_date}.md"
    filepath = feedback_dir / filename

    content = FEEDBACK_TEMPLATE.format(
        topic=topic,
        unit=unit,
        case=case,
        date=feedback_date,
        note=note,
        feedback_text=feedback_text,
    )

    filepath.write_text(content, encoding="utf-8")
    return filepath


def save_engram(topic: str, unit: str, case: str,
                feedback_date: str, filepath: Path) -> bool:
    title = f"[feedback] {topic} U{unit} {case} {feedback_date}"
    content = filepath.read_text(encoding="utf-8")

    try:
        result = subprocess.run(
            ["engram", "save", "-t", title, "-p", "digital-lab", content],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0
    except FileNotFoundError:
        print("  Engram CLI no disponible — solo guardado local")
        return False
    except Exception as e:
        print(f"  Error Engram: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Guarda feedback del evaluador")
    parser.add_argument("--topic", required=True,
                        choices=list(TOPIC_TO_FOLDER.keys()),
                        help="Topic del caso práctico")
    parser.add_argument("--unit", required=True,
                        help="Unidad o módulo (ej: 4, mod3)")
    parser.add_argument("--case", required=True,
                        help="Nombre del caso práctico")
    parser.add_argument("--note", required=True,
                        choices=["sobresaliente", "notable", "bien",
                                 "suficiente", "insuficiente"],
                        help="Nota recibida")
    parser.add_argument("--date", default=str(date.today()),
                        help="Fecha del feedback (default: hoy)")
    parser.add_argument("--feedback", default="",
                        help="Texto del feedback (inline)")
    parser.add_argument("--file", default=None,
                        help="Archivo de texto con el feedback")

    args = parser.parse_args()

    if args.file:
        feedback_text = Path(args.file).read_text(encoding="utf-8")
    elif args.feedback:
        feedback_text = args.feedback
    else:
        print("Introduce el feedback (Ctrl+D para terminar):")
        feedback_text = sys.stdin.read()

    if not feedback_text.strip():
        print("Error: feedback vacío")
        sys.exit(1)

    print(f"\nGuardando feedback...")
    print(f"  Topic:  {args.topic}")
    print(f"  Unidad: {args.unit}")
    print(f"  Caso:   {args.case}")
    print(f"  Nota:   {args.note}")
    print(f"  Fecha:  {args.date}")

    filepath = save_local(args.topic, args.unit, args.case,
                          args.note, args.date, feedback_text)
    print(f"\n  Archivo: {filepath.relative_to(BASE_DIR)}")

    engram_ok = save_engram(args.topic, args.unit, args.case, args.date, filepath)
    if engram_ok:
        print(f"  Engram:  guardado como '[feedback] {args.topic} U{args.unit} ...'")

    print(f"\nPara indexar en el RAG:")
    print(f"  cd src && python3.9 main.py index --all")
    print(f"\nPara verificar recuperación:")
    print(f"  cd src && python3.9 main.py query -q 'feedback {args.topic}' --topic {args.topic}")


if __name__ == "__main__":
    main()
