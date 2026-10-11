"""Linha de comando do PonteAnimada (`uv run ponte ...`).

É por aqui que as animações são feitas pelo backend; o que é gerado aparece na
interface para validação, e o que o humano decide lá volta em `ponte status`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import ardy, engines, jobs, kimodo, meshy, pipeline, store
from .config import DATA, KIMODO_MAX_SAMPLES, KIMODO_MODEL, SETTINGS


def _run_job(kind: str, title: str, params: dict, work) -> dict:
    """Roda no próprio processo, registrando o job para a interface acompanhar."""
    job = jobs.create(kind, title, params)

    def logged(job_id: str):
        def log(line: str) -> None:
            print(f"  · {line}", flush=True)
            jobs.log(job_id, line)

        return work(log)

    final = jobs.run(job, logged)
    if final["status"] != "ok":
        print(f"ERRO: {final['error']}", file=sys.stderr)
        sys.exit(1)
    return final["output"]


def _review_tag(record: dict) -> str:
    review = record.get("review") or {}
    tag = {"aprovado": "[aprovado]", "reprovado": "[REPROVADO]"}.get(review.get("status"), "[pendente]")
    return tag + (f' "{review["notes"]}"' if review.get("notes") else "")


def cmd_serve(args) -> None:
    import uvicorn

    uvicorn.run("ponte.server:app", host=args.host, port=args.port, log_level="warning")


def cmd_status(_args) -> None:
    k = kimodo.status()
    print(f"Kimodo  : {KIMODO_MODEL} · docker {'ok' if k['docker'] else 'parado'} · text encoder {'ok' if k['encoder'] else 'parado'} · gerando {k['generating']}/{k['limit']} · {k['queued']} na fila")
    a = ardy.status()
    if a["installed"]:
        print(f"ARDY    : {a['model']} · codificador de texto {'no ar' if a['encoder'] else 'desligado'}")
    # O usuário escolhe o gerador ao abrir a ponte.
    print("Gerador : " + " · ".join(f"{o['name']}{' (em uso)' if o['id'] == engines.current() else ''}{' [indisponível]' if o['problem'] else ''}" for o in engines.status()["options"]))
    assets, motions, results = store.list_all("asset"), store.list_all("motion"), store.list_all("result")
    closed = [a for a in assets if a.get("final")]
    print(f"Acervo  : {len(assets)} projeto(s) · {len(motions)} animação(ões) · {len(results)} prévia(s) · {len(closed)} personagem(ns) encerrado(s)")
    # Pedidos ao Meshy que ainda não viraram projeto: a imagem espera a aprovação dele, e a nota de uma reprovada diz o que mudar.
    for r in meshy.list_requests():
        if r["status"] != meshy.READY:
            print(f"Meshy   : {r['name']} ({r['id']}) · {r['status']}" + (f' "{r["note"]}"' if r.get("note") else "") + (f" · erro: {r['error']}" if r.get("error") else ""))
    active = [j for j in jobs.list_jobs() if j["status"] in jobs.ACTIVE]
    for job in active:
        print(f"Rodando : {job['title']} — {job['progress']}")
    # Cada personagem é um projeto, com as animações e as prévias dele; o resultado só existe depois de encerrado.
    for a in assets:
        s = a.get("summary") or {}
        print(f"\nProjeto {a['name']}  ({a['id']})")
        print(f"  personagem: {a.get('verdict') or a['status']} · {s.get('rig') or 'sem rig'} · {_review_tag(a)}")
        mine = [r for r in results if r["asset_id"] == a["id"]]
        loose = [m for m in motions if m.get("asset_id") == a["id"] and not any(r["motion_id"] == m["id"] for r in mine)]
        for r in mine:
            print(f"  prévia    {r['id']:<52} {_review_tag(r)}")
        for m in loose:
            # Numa corrente de passos, a animação de onde o passo seguinte partiu fica guardada sem prévia.
            longer = next((x["id"] for x in motions if x.get("continued_from") == m["id"]), None)
            print(f"  animação  {m['id']:<52} ({f'guardada: {longer} continua dela' if longer else 'ainda não aplicada'})")
        final = a.get("final")
        if final:
            stale = " · DESATUALIZADO (o projeto mudou depois)" if final.get("signature") != pipeline.final_signature(a, mine) else ""
            print(f"  resultado : encerrado em {final['at']} com {len(final['clips'])} animação(ões) · atalho {store.SHORTCUTS / final['shortcut']}{stale}")
        else:
            print("  resultado : ainda não encerrado")
    if not assets:
        print("  (vazio)")


def cmd_asset_add(args) -> None:
    extra = getattr(args, "textures", None) or []
    out = _run_job("inspecao", f"Inspecionar {args.file.name}", {}, lambda log: {"asset_id": pipeline.add_asset(args.file, args.name, log, extra)["id"]})
    print(out["asset_id"])


def cmd_asset_textures(args) -> None:
    def work(log):
        log(f"{len(pipeline.add_sidecars(args.id, args.files))} arquivo(s) copiado(s)")
        return {"asset_id": pipeline.inspect_asset(args.id, log)["id"]}

    _run_job("inspecao", f"Texturas de {args.id}", {"asset_id": args.id}, work)


def cmd_asset_show(args) -> None:
    asset = store.get("asset", args.id)
    report = store.read_json(store.folder("asset", args.id) / "report.json") or {}
    print(f"{asset['name']} ({asset['id']}) — laudo: {asset.get('verdict')} · revisão: {_review_tag(asset)}")
    for key in ("rig", "bones", "triangles", "height_m", "rest_pose"):
        print(f"  {key:<10} {(asset.get('summary') or {}).get(key)}")
    mapping = report.get("mapping") or {}
    if mapping:
        cov = mapping["coverage"]
        print(f"  mapeados   {cov['mapped']}/{cov['total']} · coluna {mapping['torso']} · pescoço {mapping['neck']}")
        if mapping["missing_required"]:
            print(f"  FALTAM     {', '.join(mapping['missing_required'])}")
    for issue in report.get("issues", []):
        print(f"  [{issue['level']}] {issue['msg']}")


def cmd_asset_inspect(args) -> None:
    _run_job("inspecao", f"Inspecionar {args.id}", {"asset_id": args.id}, lambda log: {"asset_id": pipeline.inspect_asset(args.id, log)["id"]})


def cmd_gen(args) -> None:
    """Um roteiro: cada frase do prompt é um passo, e cada passo continua o anterior."""
    travel = None
    if args.direction:
        travel = {"direction_deg": pipeline.DIRECTIONS[args.direction], "speed": args.speed, "lock_facing": not args.free_facing}
    steps = kimodo.steps_from_prompt(args.prompt, args.duration, travel, args.loop, args.text_weight)
    steps[-1]["label"] = args.label
    if args.dry_run:
        # Confere que o roteiro monta, sem carregar o modelo nem gerar nada.
        work_dir = DATA / "tmp" / "dry-run"
        script = [{**s, "text": pipeline.compose_step_text(args.premise, s["text"])} for s in steps]
        try:
            generator = engines.module(args.engine or engines.current())
            for out in generator.generate(work_dir, [{"name": "motion", "steps": script, "seed": 0}], dry_run=True, log=lambda line: print(f"  · {line}", flush=True)):
                print(f"roteiro ok: {out['frames']} quadros; passos começam em {out['step_frames']}")
        finally:
            kimodo.cleanup_work_dir(work_dir)
        return
    options = dict(premise=args.premise, seed=args.seed, samples=args.samples, continue_from=args.continue_from, replaces=args.replaces, name=args.name, engine=args.engine)

    if not args.asset:
        raise ValueError("Diga o projeto com --asset: toda animação é gerada para um personagem.")

    def work(log):
        results = pipeline.animate(args.asset, steps, in_place=args.in_place, log=log, **options)
        return {"result_ids": [r["id"] for r in results], "motion_ids": [r["motion_id"] for r in results]}

    out = _run_job("animacao", f"Gerar: {args.prompt}", {"prompt": args.prompt, "asset_id": args.asset}, work)
    for key, ids in out.items():
        print(f"{key}: {' '.join(ids)}")


def cmd_motion_import(args) -> None:
    print(pipeline.import_motion(args.asset, args.file, args.label, lambda line: print(f"  · {line}"))["id"])


def cmd_motion_import_fbx(args) -> None:
    out = _run_job(
        "retarget",
        f"Importar do Mixamo: {args.label or args.file.stem} → {args.asset}",
        {"asset_id": args.asset},
        lambda log: {"result_ids": [pipeline.import_mixamo(args.asset, args.file, args.label, log=log)["id"]]},
    )
    print(out["result_ids"][0])


def cmd_motion_import_capture(args) -> None:
    if args.loop is not None and len(args.loop) not in (0, 2):
        raise SystemExit("--loop aceita a duração mínima e a máxima do laço, em segundos, ou nada.")
    loop = False if args.loop is None else (tuple(args.loop) or True)
    out = _run_job(
        "retarget",
        f"Importar captura: {args.label or args.file.stem} → {args.asset}",
        {"asset_id": args.asset},
        lambda log: {
            "result_ids": [
                pipeline.import_capture(args.asset, args.file, args.label, start=args.start, end=args.end, loop=loop, direction=args.direction, credit=args.credit, log=log)["id"]
            ]
        },
    )
    print(out["result_ids"][0])


def cmd_motion_label(args) -> None:
    motion = pipeline.label_motion(args.id, args.name, args.steps)
    print(f"{motion.get('name') or '(sem nome)'}: " + " · ".join(s.get("label") or "?" for s in motion.get("steps") or []))


def cmd_motion_list(args) -> None:
    for m in store.list_all("motion", args.asset):
        print(f"  {m['id']:<44} {m['duration_s']:>5}s  {m.get('asset_id', '?'):<30} {m.get('prompt', '')}")


def cmd_retarget(args) -> None:
    out = _run_job(
        "retarget",
        f"Retarget {args.motion} → {args.asset}",
        {"asset_id": args.asset, "motion_id": args.motion},
        lambda log: {"result_ids": [pipeline.retarget(args.asset, args.motion, in_place=args.in_place, log=log)["id"]]},
    )
    print(out["result_ids"][0])


def cmd_anim_add(args) -> None:
    """Uma animação feita no Blender, já no personagem, entra na tela do projeto como está."""
    result = pipeline.add_ready_animation(args.asset, args.file, args.name, blend=args.blend, replace=args.replace, log=lambda line: print(f"  · {line}", flush=True))
    print(result["id"])


def _free_project(asset_id: str) -> dict:
    asset = store.get("asset", asset_id)
    busy = pipeline.active_jobs(asset_id)
    if busy:
        raise ValueError(f"Ainda há trabalho rodando neste projeto ({'; '.join(j['title'] for j in busy)}). Espere terminar.")
    return asset


def cmd_close(args) -> None:
    """Encerra o personagem: o resultado nasce aqui, com todas as animações num arquivo só."""
    asset = _free_project(args.id)
    if args.unreal is not None:
        pipeline.set_unreal(args.id, args.unreal)
    out = _run_job("encerramento", f"Encerrar {asset['name']}", {"asset_id": args.id}, lambda log: {"asset_id": args.id, "final": pipeline.close_project(args.id, log)["final"]})
    final = out["final"]
    print(f"resultado: {store.final_folder(args.id)}  ({', '.join(final['files'].values())})")
    if final.get("unreal"):
        print(f"unreal 5 : {store.final_folder(args.id) / final['unreal']['file']}  ({final['unreal']['bones']} ossos, esqueleto do Mannequin)")
    print(f"atalho   : {store.SHORTCUTS / final['shortcut']}")
    for clip in final["clips"]:
        print(f"  {clip['name']:<50} {clip['duration_s']:>6}s  [{clip['review']}]")
    if final["rejected"]:
        print(f"  de fora (reprovadas): {', '.join(final['rejected'])}")


def cmd_reopen(args) -> None:
    _free_project(args.id)
    pipeline.reopen_project(args.id)
    print(f"reaberto: {args.id} (o resultado e o atalho foram removidos; o projeto ficou como estava)")


def cmd_delete(args) -> None:
    store.get(args.kind, args.id)
    pipeline.delete(args.kind, args.id)
    print(f"apagado: {args.kind} {args.id}")


def cmd_kimodo(args) -> None:
    if args.action == "start":
        kimodo.ensure_ready(lambda line: print(f"  · {line}", flush=True))
    elif args.action == "stop":
        print(kimodo.stop())
    print(kimodo.status())


def cmd_ardy(args) -> None:
    """O ARDY: o codificador de texto dele e as sessões exportadas pelo demo ao vivo."""
    if args.action == "start":
        ardy.start_encoder(lambda line: print(f"  · {line}", flush=True))
    elif args.action == "stop":
        print(ardy.stop())
    elif args.action == "sessions":
        found = ardy.sessions()
        print(f"Sessões do demo ao vivo em {found['folder']} (no Ubuntu):")
        for s in found["sessions"]:
            if s.get("error"):
                print(f"  {s['file']:<40} ilegível: {s['error']}")
            else:
                print(f"  {s['file']:<40} {s['seconds']:>6g} s  {s['modified'][:16].replace('T', ' ')}  {' → '.join(s['prompts']) or '(sem texto)'}")
        if not found["sessions"]:
            print("  (nenhuma: no demo, aba IO, botão Export Session)")
        return
    s = ardy.status()
    print(f"ARDY    : {'instalado' if s['installed'] else 'não instalado'} · {s['model']} · codificador de texto {'no ar' if s['encoder'] else 'desligado (sobe sozinho para texto novo)'}")


def cmd_motion_import_ardy(args) -> None:
    session = args.session
    if not session:
        found = [s for s in ardy.sessions()["sessions"] if not s.get("error")]
        if not found:
            raise ValueError("Não há sessão exportada pelo demo do ARDY (no demo: aba IO, botão Export Session).")
        session = found[0]["file"]  # a mais recente
        print(f"  · sessão mais recente: {session}")
    out = _run_job(
        "retarget",
        f"Importar do ARDY: {args.label or Path(session).stem} → {args.asset}",
        {"asset_id": args.asset},
        lambda log: {"result_ids": [pipeline.import_ardy_session(args.asset, session, args.label, start=args.start, end=args.end, log=log)["id"]]},
    )
    print(out["result_ids"][0])


def cmd_meshy(args) -> None:
    """Personagem pelo Meshy, em duas etapas: a imagem, que o usuário aprova, e só então o modelo 3D."""

    def need(what: str) -> str:
        if not args.value:
            raise ValueError(f"Diga {what}.")
        return args.value

    if args.action == "key":
        meshy.save_key(need("a chave da API do Meshy"))
        left = meshy.balance()
        print(f"chave guardada em {meshy.KEY_FILE} (fora do git)" + (f" · {left} créditos na conta" if left is not None else " · o Meshy não confirmou a chave: confira"))
    elif args.action == "image":
        prompt = need("o que a imagem deve mostrar, em inglês")
        out = _run_job(
            "meshy",
            f"Meshy: imagem de {args.name or prompt[:40]}",
            {},
            lambda log: {"meshy_request": meshy.request_image(prompt, args.name, pose=args.pose, ai_model=args.model, replaces=args.replaces, log=log)["id"]},
        )
        record = meshy.get(out["meshy_request"])
        print(f"pedido {record['id']}: imagem em {meshy.REQUESTS / record['id'] / record['image']}")
        print("aguardando a aprovação do usuário: Pedidos ao Meshy, na tela de entrada da ponte")
    elif args.action == "approve":
        record = meshy.get(need("o id do pedido"))
        if record["status"] == meshy.BUILDING and any(j["status"] in jobs.ACTIVE and (j.get("params") or {}).get("meshy_request") == record["id"] for j in jobs.list_jobs()):
            raise ValueError("O modelo 3D deste pedido já está sendo gerado.")
        out = _run_job("meshy", f"Meshy: modelo 3D de {record['name']}", {"meshy_request": record["id"]}, lambda log: {"asset_id": pipeline.approve_meshy(record["id"], polycount=args.polycount, log=log)["id"]})
        print(f"projeto criado: {out['asset_id']}")
    elif args.action == "reject":
        record = meshy.reject(need("o id do pedido"), args.note or "")
        print(f"reprovado: {record['id']}" + (f' "{record["note"]}"' if record["note"] else ""))
    elif args.action == "delete":
        meshy.delete(meshy.get(need("o id do pedido"))["id"])
        print(f"tirado da lista: {args.value}")
    else:
        left = meshy.balance() if meshy.api_key() else None
        print("Meshy   : " + ("sem chave (crie em https://www.meshy.ai/developers/keys e guarde com `ponte meshy key <chave>`)" if not meshy.api_key() else f"chave ok · {left if left is not None else '?'} créditos"))
        for r in meshy.list_requests():
            print(f"  {r['id']:<40} {r['status']:<22} {r['name']}" + (f' · nota: "{r["note"]}"' if r.get("note") else "") + (f" · erro: {r['error']}" if r.get("error") else "") + (f" · projeto {r['asset_id']}" if r.get("asset_id") else ""))


def cmd_engine(args) -> None:
    """Mostra os geradores ou troca o que está em uso (o que o usuário escolhe ao abrir a ponte)."""
    if args.name:
        engines.choose(args.name)
    for option in engines.status()["options"]:
        mark = "em uso" if option["id"] == engines.current() else "      "
        print(f"[{mark}] {option['id']:<7} {option['name']}: {option['about']}" + (f"\n         INDISPONÍVEL. {option['problem']}" if option["problem"] else ""))


def cmd_fixture(args) -> None:
    """Gera o boneco de teste e o registra como asset."""
    from . import blender

    out = DATA / "tmp" / "boneco_de_teste.fbx"
    blender.run_script("make_test_rig.py", ["--out", out, "--pose", args.pose], out.with_suffix(".make.json"))
    cmd_asset_add(argparse.Namespace(file=out, name="Boneco de teste"))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    store.migrate_layout_safely()  # acervo do formato antigo vai para a pasta do projeto dele
    ap = argparse.ArgumentParser(prog="ponte", description="Ponte entre Blender, Kimodo e a validação humana.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("serve", help="sobe a interface web")
    p.add_argument("--host", default=SETTINGS.host)
    p.add_argument("--port", type=int, default=SETTINGS.port)
    p.set_defaults(fn=cmd_serve)

    sub.add_parser("status", help="acervo, revisões e jobs em andamento").set_defaults(fn=cmd_status)

    asset = sub.add_parser("asset", help="assets 3D").add_subparsers(dest="sub", required=True)
    p = asset.add_parser("add", help="registra e inspeciona um arquivo")
    p.add_argument("file", type=Path)
    p.add_argument("--name")
    p.add_argument("--textures", type=Path, nargs="+", help="arquivos de textura ou a pasta delas")
    p.set_defaults(fn=cmd_asset_add)
    p = asset.add_parser("textures", help="acrescenta texturas a um asset e refaz o laudo")
    p.add_argument("id")
    p.add_argument("files", type=Path, nargs="+", help="arquivos ou pasta")
    p.set_defaults(fn=cmd_asset_textures)
    p = asset.add_parser("show", help="laudo do asset")
    p.add_argument("id")
    p.set_defaults(fn=cmd_asset_show)
    p = asset.add_parser("inspect", help="refaz o laudo")
    p.add_argument("id")
    p.set_defaults(fn=cmd_asset_inspect)

    p = sub.add_parser("gen", help="gera uma animação no Kimodo (e aplica num asset, se --asset)")
    p.add_argument("prompt", help="em inglês; cada frase terminada em ponto é um passo do roteiro, que continua o anterior")
    p.add_argument("--premise", default="", help="contexto repetido em todo passo (ex.: \"A soldier aiming a rifle\")")
    p.add_argument("--dry-run", action="store_true", help="só confere que o roteiro monta; não gera nada")
    p.add_argument("--engine", choices=sorted(engines.ENGINES), help="o gerador: o Kimodo original (kimodo), o kimodo.cpp (cpp) ou o ARDY (ardy). Padrão: o que o usuário escolheu ao abrir a ponte (ver `ponte engine`)")
    p.add_argument("--duration", type=float, nargs="+", default=[5.0], help="segundos; um valor, ou um por passo")
    p.add_argument("--seed", type=int)
    p.add_argument("--samples", type=int, default=1, choices=range(1, KIMODO_MAX_SAMPLES + 1))
    p.add_argument("--asset", help="id do projeto (o do personagem): a animação é gerada para ele")
    p.add_argument("--in-place", action="store_true", help="sem deslocamento horizontal")
    p.add_argument("--direction", choices=list(pipeline.DIRECTIONS), help="todos os passos andam em linha reta nessa direção (relativa a para onde ele olha)")
    p.add_argument("--speed", type=float, default=1.2, help="m/s, com --direction (andar ~1.2, correr ~3.5)")
    p.add_argument("--free-facing", action="store_true", help="com --direction: deixa o corpo virar em vez de travá-lo para frente")
    p.add_argument("--name", help="nome do roteiro, para achá-lo na interface (ex.: Reações); numa continuação, sem ele vale o que já tinha")
    p.add_argument("--label", help="nome do passo, em português (ex.: agitado)")
    p.add_argument("--text-weight", type=float, metavar="PESO", help="quanto o Kimodo obedece ao texto (padrão dele: 2). Mais peso dá um gesto mais marcado")
    p.add_argument("--loop", action="store_true", help="o passo termina na pose em que começou, para o jogo tocar em laço; precisa de --continue (o laço fecha no fim do passo anterior)")
    p.add_argument("--continue", dest="continue_from", metavar="ANIMACAO", help="id da animação a continuar: a nova começa onde ela termina, e a prévia dela sai da lista")
    p.add_argument("--replace", dest="replaces", metavar="ANIMACAO", help="id da animação que este pedido refaz: é apagada, com as prévias, quando a nova fica pronta")
    p.set_defaults(fn=cmd_gen)

    motion = sub.add_parser("motion", help="animações").add_subparsers(dest="sub", required=True)
    p = motion.add_parser("import", help="registra no projeto um BVH do Kimodo (SOMA 77) já existente")
    p.add_argument("asset", help="id do projeto (o do personagem)")
    p.add_argument("file", type=Path)
    p.add_argument("--label")
    p.set_defaults(fn=cmd_motion_import)
    p = motion.add_parser("import-fbx", help="traz uma animação pronta em FBX (as do Mixamo) e a aplica no personagem do projeto")
    p.add_argument("asset", help="id do projeto (o do personagem)")
    p.add_argument("file", type=Path)
    p.add_argument("--label", help="nome da ação (padrão: o nome do arquivo)")
    p.set_defaults(fn=cmd_motion_import_fbx)
    p = motion.add_parser("import-capture", help="traz uma captura de movimento em BVH (esqueleto qualquer), recorta e a aplica no personagem do projeto")
    p.add_argument("asset", help="id do projeto (o do personagem)")
    p.add_argument("file", type=Path)
    p.add_argument("--label", help="nome da ação (padrão: o nome do arquivo)")
    p.add_argument("--start", type=float, metavar="S", help="segundo do arquivo em que o trecho começa")
    p.add_argument("--end", type=float, metavar="S", help="segundo do arquivo em que o trecho termina")
    p.add_argument("--loop", type=float, nargs="*", metavar="S", help="fica só o melhor laço do trecho, já fechado; opcionalmente a duração mínima e a máxima (padrão: 0.6 4)")
    p.add_argument("--direction", choices=sorted(pipeline.DIRECTIONS), help="para onde anda um laço que se desloca (padrão: a mais próxima entre frente, lados e trás)")
    p.add_argument("--credit", help="crédito que a licença do arquivo pede; fica no registro da animação")
    p.set_defaults(fn=cmd_motion_import_capture)
    p = motion.add_parser("import-ardy", help="traz uma sessão exportada pelo demo ao vivo do ARDY e a aplica no personagem do projeto")
    p.add_argument("asset", help="id do projeto (o do personagem)")
    p.add_argument("session", nargs="?", help="arquivo da sessão (ver `ponte ardy sessions`); sem ele, a mais recente")
    p.add_argument("--label", help="nome do roteiro (padrão: o nome do arquivo)")
    p.add_argument("--start", type=float, metavar="S", help="segundo da sessão em que o trecho começa")
    p.add_argument("--end", type=float, metavar="S", help="segundo da sessão em que o trecho termina")
    p.set_defaults(fn=cmd_motion_import_ardy)
    p = motion.add_parser("label", help="dá nome ao roteiro e aos passos dele, para achar cada trecho na interface")
    p.add_argument("id")
    p.add_argument("--name", help="nome do roteiro")
    p.add_argument("--steps", nargs="+", metavar="NOME", help="nome de cada passo, na ordem")
    p.set_defaults(fn=cmd_motion_label)
    p = motion.add_parser("list")
    p.add_argument("--asset", help="só as animações deste projeto")
    p.set_defaults(fn=cmd_motion_list)

    anim = sub.add_parser("anim", help="animações prontas, feitas no Blender: entram na tela do projeto como estão").add_subparsers(dest="sub", required=True)
    p = anim.add_parser("add", help="põe na tela do projeto um GLB com o personagem já animado (sem retarget)")
    p.add_argument("asset", help="id do projeto (o do personagem)")
    p.add_argument("file", type=Path, help="o .glb, com o personagem, os acessórios e a animação")
    p.add_argument("--name", help="nome da animação na tela (padrão: o nome do arquivo)")
    p.add_argument("--blend", type=Path, help="o arquivo do Blender de onde ela saiu, para ficar guardado junto")
    p.add_argument("--replace", action="store_true", help="troca a animação pronta de mesmo nome que já estiver no projeto")
    p.set_defaults(fn=cmd_anim_add)

    p = sub.add_parser("retarget", help="aplica uma animação do projeto no personagem dele (a prévia que o humano valida)")
    p.add_argument("asset")
    p.add_argument("motion")
    p.add_argument("--in-place", action="store_true")
    p.set_defaults(fn=cmd_retarget)

    p = sub.add_parser("close", help="encerra o personagem: monta o resultado (as prévias não reprovadas num arquivo só) e cria o atalho dele")
    p.add_argument("id", help="id do projeto (o do personagem)")
    p.add_argument("--unreal", action=argparse.BooleanOptionalAction, default=None, help="liga o arquivo para a Unreal 5, com o esqueleto do Mannequin (--no-unreal desliga); fica valendo para o personagem")
    p.set_defaults(fn=cmd_close)
    p = sub.add_parser("reopen", help="desfaz o encerramento: remove o resultado e o atalho")
    p.add_argument("id", help="id do projeto (o do personagem)")
    p.set_defaults(fn=cmd_reopen)

    p = sub.add_parser("delete", help="apaga um item (e as prévias que dependem dele)")
    p.add_argument("kind", choices=sorted(store.KINDS))
    p.add_argument("id")
    p.set_defaults(fn=cmd_delete)

    p = sub.add_parser("kimodo", help="liga, desliga ou consulta o Kimodo")
    p.add_argument("action", choices=("status", "start", "stop"))
    p.set_defaults(fn=cmd_kimodo)

    p = sub.add_parser("meshy", help="personagem pelo Meshy em duas etapas: a imagem (image), que o usuário aprova na tela, e só então o modelo 3D (approve), que vira projeto")
    p.add_argument("action", choices=("status", "key", "image", "approve", "reject", "delete"))
    p.add_argument("value", nargs="?", help="image: o texto do pedido, em inglês; approve, reject, delete: o id do pedido; key: a chave da API")
    p.add_argument("--name", help="com image: o nome do personagem (vira o nome do projeto)")
    p.add_argument("--pose", choices=meshy.POSES, default="a-pose", help="com image: a pose, com os braços afastados do corpo, para o rig (padrão: a-pose)")
    p.add_argument("--model", choices=meshy.IMAGE_MODELS, default=meshy.IMAGE_MODEL, help="com image: o modelo de imagem (padrão: o mais barato)")
    p.add_argument("--replace", dest="replaces", metavar="PEDIDO", help="com image: o pedido reprovado que este refaz; ele sai da lista quando a imagem nova chega")
    p.add_argument("--note", help="com reject: o que mudar")
    p.add_argument("--polycount", type=int, default=meshy.POLYCOUNT, metavar="N", help=f"com approve: triângulos do modelo (padrão {meshy.POLYCOUNT}; 0 deixa como o Meshy gerar)")
    p.set_defaults(fn=cmd_meshy)

    p = sub.add_parser("ardy", help="o ARDY: consulta, liga ou desliga o codificador de texto dele, ou lista as sessões do demo ao vivo")
    p.add_argument("action", choices=("status", "start", "stop", "sessions"))
    p.set_defaults(fn=cmd_ardy)

    p = sub.add_parser("engine", help="mostra ou troca o gerador em uso: o Kimodo original (kimodo), o kimodo.cpp (cpp) ou o ARDY (ardy)")
    p.add_argument("name", nargs="?", choices=sorted(engines.ENGINES))
    p.set_defaults(fn=cmd_engine)

    p = sub.add_parser("fixture", help="gera e registra o boneco de teste")
    p.add_argument("--pose", choices=("A", "T"), default="A")
    p.set_defaults(fn=cmd_fixture)

    args = ap.parse_args()
    try:
        args.fn(args)
    except (KeyError, ValueError, kimodo.KimodoError, meshy.MeshyError) as exc:
        print(f"ERRO: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
