#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline mestre de atualizacao dos bancos de dados.

Este arquivo e o ponto unico para atualizar as bases locais. Ele carrega os
scripts por importlib quando eles possuem uma funcao de entrada reutilizavel e
mantem um modo legado para scripts antigos que ainda executam pelo bloco
``if __name__ == "__main__"``.

Uso:
  python3 000_pipeline_final.py --all
  python3 000_pipeline_final.py --stage discursos
  python3 000_pipeline_final.py --script 16_presenca.py
  python3 000_pipeline_final.py --dry-run --all
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import inspect
import logging
import os
import runpy
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

PIPELINE_LOG = LOG_DIR / "pipeline_maestro.log"
LOCK_FILE = BASE_DIR / ".pipeline.lock"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(PIPELINE_LOG, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("pipeline")


class Tee:
    """Duplica stdout/stderr para console e arquivo de log do passo."""

    def __init__(self, *streams: Any) -> None:
        self.streams = streams

    def write(self, data: str) -> int:
        for stream in self.streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


@dataclass(frozen=True)
class PipelineStep:
    path: str
    entrypoint: str | None = "main"
    description: str = ""
    mode: str = "import"
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.path


def _module_name_for(path: Path) -> str:
    safe = path.with_suffix("").as_posix().replace("/", "_").replace("-", "_")
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in safe)
    return f"pipeline_step_{safe}"


def import_script(step: PipelineStep) -> ModuleType:
    script_path = BASE_DIR / step.path
    if not script_path.exists():
        raise FileNotFoundError(f"Script nao encontrado: {step.path}")

    module_name = _module_name_for(script_path.relative_to(BASE_DIR))
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Nao foi possivel importar {step.path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_callable(module: ModuleType, step: PipelineStep) -> Callable[..., Any]:
    if not step.entrypoint:
        raise AttributeError(f"{step.path} nao declarou entrypoint")
    target = getattr(module, step.entrypoint, None)
    if not callable(target):
        raise AttributeError(f"{step.path} nao possui funcao '{step.entrypoint}'")
    return target


def _run_result(result: Any) -> None:
    if inspect.isawaitable(result):
        asyncio.run(result)


def run_imported_step(step: PipelineStep) -> None:
    script_path = BASE_DIR / step.path
    old_argv = sys.argv[:]
    try:
        sys.argv = [str(script_path), *map(str, step.args)]
        module = import_script(step)

        if step.path == "04_CHROMA_DB.py" and step.entrypoint == "run":
            # O script ja expoe run(), mas seus defaults vivem como constantes do modulo.
            step = PipelineStep(
                path=step.path,
                entrypoint=step.entrypoint,
                description=step.description,
                mode=step.mode,
                kwargs={
                    "db_path": module.DEFAULT_DB_PATH,
                    "docs_per_batch": module.DOCS_PER_BATCH,
                    "embed_batch_size": module.EMBED_BATCH_SIZE,
                    "force_reset": False,
                    "test_limit": None,
                },
            )

        target = _resolve_callable(module, step)
        _run_result(target(*step.args, **step.kwargs))
    finally:
        sys.argv = old_argv


def run_legacy_main(step: PipelineStep) -> None:
    script_path = BASE_DIR / step.path
    if not script_path.exists():
        raise FileNotFoundError(f"Script nao encontrado: {step.path}")

    old_argv = sys.argv[:]
    try:
        sys.argv = [str(script_path), *map(str, step.args)]
        runpy.run_path(str(script_path), run_name="__main__")
    finally:
        sys.argv = old_argv


PIPELINE_STAGES: dict[str, list[PipelineStep]] = {
    "core": [
        PipelineStep("00_tabelao.py", mode="legacy", description="Atualiza tabelao.db"),
    ],
    "legislativo": [
        PipelineStep("20_projetos_lei.py", "processar", description="Projetos de lei"),
        PipelineStep("15_votacao.py", "main", description="Votacoes unificadas"),
        PipelineStep("24_votacao_total_parlamentares.py", "process_votes", description="Votos nominais e simbolicos"),
        PipelineStep("16_presenca.py", "processar_presencas", description="Presencas e comissoes"),
        PipelineStep("17_ajuste_comissao.py", "main", description="Normalizacao de comissoes"),
    ],
    "noticias": [
        PipelineStep("01_Coleta_Noticias.py", mode="legacy", description="Coleta de noticias"),
        PipelineStep("02_Limpeza_Fuzz_Nominal.py", mode="legacy", description="Limpeza nominal"),
        PipelineStep("03_Recuperacao_Textual_Fuzz.py", mode="legacy", description="Recuperacao textual"),
        PipelineStep("04_Auditoria_Profunda_GPT4.py", mode="legacy", description="Auditoria de noticias"),
    ],
    "discursos": [
        PipelineStep("02_scraper_discursos_final.py", mode="legacy", description="Scraping de discursos"),
        PipelineStep("03_banco_do_md.py", "main", description="Ingestao dos markdowns no discursos.db"),
        PipelineStep("04_CHROMA_DB.py", "run", description="Indice vetorial Chroma"),
        PipelineStep("05_LIGHT_RAG_BATCH_OPENAI_BATCH_API.py", "main", description="Batch LLM dos discursos"),
        PipelineStep("06_normalizacao_nomes_citados_BATCH_API.py", "main", description="Normalizacao de citacoes"),
        PipelineStep("07_normalizacao_citacoes_discursos_integrados_BATCH_API.py", "main", description="Integracao das citacoes"),
        PipelineStep("08_verificacao_contexto_ambiguo_BATCH_API.py", "main", description="Verificacao de ambiguidades"),
    ],
    "auditoria": [
        PipelineStep("14_emendas.py", mode="legacy", description="Emendas parlamentares"),
        PipelineStep("05_cruzamento_emendas_socios.py", mode="legacy", description="Cruzamento emendas/socios"),
        PipelineStep("27_doacao.py", "main", description="Doacoes eleitorais"),
        PipelineStep("29_processos.py", "main", description="Processos judiciais"),
        PipelineStep("30_empresas_deep.py", "main", description="Auditoria profunda de empresas"),
        PipelineStep("31_assessores.py", "main", description="Assessores parlamentares"),
        PipelineStep("32_sancoes.py", "main", description="Sancoes CEIS/CEPIM"),
        PipelineStep("35_investigador_passageiros_osint.py", "main", description="OSINT de passageiros"),
    ],
}


OBSOLETE_OR_OUT_OF_PIPELINE = {
    "archive_noticias/": "Arquivo historico; nao roda no pipeline mestre.",
    "scratch/": "Experimentos locais.",
    "check_*.py": "Scripts de inspecao/diagnostico.",
    "debug_*.py": "Scripts de diagnostico.",
    "verify_*.py": "Scripts de verificacao pontual.",
    "teste_*.py": "Scripts de teste manual.",
    "fix_*.py": "Correcoes pontuais; executar manualmente se necessario.",
    "main.py": "Backend/API, nao atualizador de banco.",
    "mapa_server.py": "Servidor de mapa, nao atualizador de banco.",
}


def iter_steps(stage: str) -> list[PipelineStep]:
    if stage == "all":
        ordered: list[PipelineStep] = []
        for stage_name in PIPELINE_STAGES:
            ordered.extend(PIPELINE_STAGES[stage_name])
        return ordered
    return PIPELINE_STAGES[stage]


def step_log_path(step: PipelineStep) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = step.path.replace("/", "__").replace(".py", "")
    return LOG_DIR / f"pipeline_{stamp}_{safe_name}.log"


def run_step(step: PipelineStep, dry_run: bool = False) -> bool:
    logger.info("Iniciando: %s%s", step.label, f" | {step.description}" if step.description else "")
    if dry_run:
        logger.info("DRY-RUN: %s [%s]", step.label, step.mode)
        return True

    started_at = time.time()
    log_path = step_log_path(step)

    try:
        with log_path.open("w", encoding="utf-8") as step_log:
            step_log.write(f"# {step.label}\n# inicio: {datetime.now().isoformat(timespec='seconds')}\n\n")
            with contextlib.redirect_stdout(Tee(sys.stdout, step_log)), contextlib.redirect_stderr(Tee(sys.stderr, step_log)):
                if step.mode == "legacy":
                    run_legacy_main(step)
                elif step.mode == "import":
                    run_imported_step(step)
                else:
                    raise ValueError(f"Modo desconhecido para {step.path}: {step.mode}")

        elapsed = time.time() - started_at
        logger.info("Concluido: %s (%.1fs) | log: %s", step.label, elapsed, log_path)
        return True
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        elapsed = time.time() - started_at
        if code == 0:
            logger.info("Concluido: %s (%.1fs) | log: %s", step.label, elapsed, log_path)
            return True
        logger.exception("Falha: %s saiu com codigo %s | log: %s", step.label, code, log_path)
        return False
    except Exception:
        logger.exception("Falha: %s | log: %s", step.label, log_path)
        return False


def run_pipeline(stage: str, dry_run: bool = False, keep_going: bool = False) -> bool:
    ok = True
    for step in iter_steps(stage):
        if not run_step(step, dry_run=dry_run):
            ok = False
            if not keep_going:
                logger.error("Pipeline interrompido no passo: %s", step.label)
                break
    return ok


def print_plan(stage: str) -> None:
    print(f"Plano de execucao: {stage}")
    for index, step in enumerate(iter_steps(stage), start=1):
        detail = f" - {step.description}" if step.description else ""
        entrypoint = "__main__" if step.mode == "legacy" else step.entrypoint or "__main__"
        print(f"{index:02d}. {step.path} [{step.mode}:{entrypoint}]{detail}")


def print_obsolete() -> None:
    print("Fora do pipeline mestre:")
    for pattern, reason in OBSOLETE_OR_OUT_OF_PIPELINE.items():
        print(f"- {pattern}: {reason}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline mestre dos bancos de dados")
    parser.add_argument("--all", action="store_true", help="Executa todos os estagios em sequencia")
    parser.add_argument("--stage", choices=PIPELINE_STAGES.keys(), help="Executa um estagio especifico")
    parser.add_argument("--script", help="Executa um script cadastrado pelo nome do arquivo")
    parser.add_argument("--dry-run", action="store_true", help="Mostra/valida a sequencia sem executar")
    parser.add_argument("--keep-going", action="store_true", help="Continua mesmo se um passo falhar")
    parser.add_argument("--list", action="store_true", help="Lista a sequencia do pipeline")
    parser.add_argument("--list-obsolete", action="store_true", help="Lista grupos fora do pipeline")
    return parser.parse_args()


def find_script_step(script_name: str) -> PipelineStep:
    matches = [step for step in iter_steps("all") if step.path == script_name or Path(step.path).name == script_name]
    if not matches:
        raise ValueError(f"Script nao cadastrado no pipeline: {script_name}")
    if len(matches) > 1:
        raise ValueError(f"Nome ambiguo no pipeline: {script_name}")
    return matches[0]


def main() -> int:
    args = parse_args()

    if args.list_obsolete:
        print_obsolete()
        return 0

    selected_stage = "all" if args.all else args.stage

    if args.list:
        print_plan(selected_stage or "all")
        return 0

    if not selected_stage and not args.script:
        print_plan("all")
        print("\nUse --all, --stage, --script ou --dry-run.")
        return 0

    if LOCK_FILE.exists() and not args.dry_run:
        logger.error("O pipeline ja esta em execucao: %s", LOCK_FILE)
        return 1

    try:
        if not args.dry_run:
            LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")

        if args.script:
            success = run_step(find_script_step(args.script), dry_run=args.dry_run)
        else:
            assert selected_stage is not None
            success = run_pipeline(selected_stage, dry_run=args.dry_run, keep_going=args.keep_going)

        return 0 if success else 1
    finally:
        if not args.dry_run and LOCK_FILE.exists():
            LOCK_FILE.unlink()
        logger.info("Pipeline mestre finalizado.")


if __name__ == "__main__":
    raise SystemExit(main())
