"""Personagem pelo Meshy: primeiro a imagem, e o modelo 3D só depois de aprovada.

O Meshy não é chamado: no lugar da rede entra um dublê que responde como a API dele (tarefa
criada, na fila, em andamento, pronta) e entrega uma imagem e um GLB. Num acervo descartável
(PONTE_DATA), confere:

- sem chave, a ponte diz como pôr a chave e não cria pedido; a chave fica fora de ``data/``;
- o pedido gera só a imagem, que fica aguardando aprovação: nenhum modelo é pedido antes dela;
- reprovada, a nota fica guardada e o modelo não pode ser gerado; o pedido que a refaz toma o lugar;
- aprovada, a imagem vira o modelo (a partir da tarefa da imagem, na pose pedida, com a malha
  reduzida) e o modelo vira um projeto novo, com laudo; aprovar duas vezes não pede dois modelos;
- se o Meshy desiste da tarefa, o pedido volta a aguardar aprovação; se só a rede cai, a mesma
  tarefa é retomada, sem pedir (nem pagar) outra.

    uv run python tests/check_meshy.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    work = Path(tempfile.mkdtemp(prefix="ponte-meshy-"))
    os.environ["PONTE_DATA"] = str(work / "data")
    os.environ.pop("MESHY_API_KEY", None)

    from ponte import blender, meshy, pipeline, store

    problems: list[str] = []
    posts: list[tuple[str, dict]] = []  # o que foi pedido ao "Meshy"
    polls: dict[str, int] = {}
    plan: dict[str, list[str]] = {}  # por tarefa, as respostas que faltam dar
    files: dict[str, bytes] = {"https://assets.meshy.test/imagem.png": b"\x89PNG imagem de teste"}

    def expect(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    def step(text: str) -> None:
        print(f"  · {text}", flush=True)

    def refused(action, *errors) -> bool:
        try:
            action()
        except errors or (ValueError, meshy.MeshyError):
            return True
        return False

    def fake_http(method: str, url: str, body: dict | None = None, *, timeout: float = 60.0) -> bytes:
        """No lugar da rede: a API do Meshy e o servidor de arquivos dele."""
        if not url.startswith("/"):
            return files[url]
        if not meshy.api_key():
            raise meshy.MeshyError("Falta a chave da API do Meshy.")
        if url == "/openapi/v1/balance":
            return b'{"balance": 500}'
        kind = url.split("/")[3]
        if method == "POST":
            posts.append((kind, body))
            task = f"{kind}-{len(posts)}"
            plan.setdefault(task, ["PENDING", "IN_PROGRESS", "SUCCEEDED"])
            return json.dumps({"result": task}).encode()
        task = url.rsplit("/", 1)[1]
        polls[task] = polls.get(task, 0) + 1
        answers = plan[task]
        status = answers.pop(0) if len(answers) > 1 else answers[0]
        if status == "REDE":
            raise meshy.MeshyError("Não consegui falar com o Meshy: rede fora do ar")
        reply = {"id": task, "status": status, "progress": {"PENDING": 0, "IN_PROGRESS": 50}.get(status, 100), "preceding_tasks": 2, "consumed_credits": 3 if kind == "text-to-image" else 30}
        if status == "FAILED":
            reply["task_error"] = {"message": "a imagem não serve para um modelo"}
        if status == "SUCCEEDED":
            reply.update({"image_urls": ["https://assets.meshy.test/imagem.png"]} if kind == "text-to-image" else {"model_urls": {"glb": "https://assets.meshy.test/modelo.glb"}})
        return json.dumps(reply).encode()

    real = (meshy._http, meshy.KEY_FILE, meshy.time.sleep)
    meshy._http, meshy.KEY_FILE, meshy.time.sleep = fake_http, work / "meshy.key", lambda _seconds: None
    try:
        # 1) Sem chave não há pedido; a chave é conferida e fica fora do acervo.
        expect(refused(lambda: meshy.request_image("A zombie girl, full body")) and meshy.list_requests() == [], "sem chave, criou pedido ou não disse o que falta")
        expect(refused(lambda: meshy.save_key("qualquer coisa")), "aceitou como chave um texto qualquer")
        meshy.save_key("msy_chave_de_teste_0000000000")
        expect(meshy.api_key() == "msy_chave_de_teste_0000000000" and meshy.balance() == 500 and meshy.status()["configured"], "a chave guardada não foi lida de volta")
        expect(store.DATA not in meshy.KEY_FILE.parents, "a chave ficou dentro do acervo, que a interface serve")

        # 2) Etapa 1: só a imagem. Nenhum modelo é pedido antes da aprovação.
        expect(refused(lambda: meshy.request_image("A zombie girl", pose="sentada")), "aceitou uma pose que o Meshy não tem")
        first = meshy.request_image("A zombie girl, full body, torn dress", "Zumbi Teste", log=step)
        expect(posts == [("text-to-image", {"ai_model": "nano-banana", "prompt": "A zombie girl, full body, torn dress", "pose_mode": "a-pose", "aspect_ratio": "3:4"})], f"o pedido da imagem não foi como devia: {posts}")
        expect((first["status"], first["name"], first["image"]) == (meshy.WAITING, "Zumbi Teste", "imagem.png") and polls[first["image_task"]] == 3, f"a imagem não ficou aguardando aprovação: {first['status']}, {polls}")
        image = meshy.REQUESTS / first["id"] / "imagem.png"
        expect(image.read_bytes() == files["https://assets.meshy.test/imagem.png"], "a imagem não foi baixada para a pasta do pedido")
        shown = meshy.status()["requests"]
        expect([r["id"] for r in shown] == [first["id"]] and shown[0]["files_base"] == f"/files/meshy/{first['id']}", "a interface não recebe o pedido com o endereço da imagem")

        # 3) Reprovada: a nota fica, o modelo não sai, e o pedido que a refaz toma o lugar.
        meshy.reject(first["id"], "  sem o vestido rasgado ")
        expect((meshy.get(first["id"])["status"], meshy.get(first["id"])["note"]) == (meshy.REJECTED, "sem o vestido rasgado"), "a reprovação não guardou a nota")
        expect(refused(lambda: pipeline.approve_meshy(first["id"], log=step)) and len(posts) == 1, "gerou o modelo de uma imagem reprovada")
        second = meshy.request_image("A zombie girl, full body, plain dress", "Zumbi Teste", replaces=first["id"], log=step)
        expect([r["id"] for r in meshy.list_requests()] == [second["id"]], "o pedido refeito não tomou o lugar do reprovado")

        # 4) Aprovada: a imagem vira o modelo, e o modelo vira um projeto novo.
        rig = work / "boneco.fbx"
        blender.run_script("make_test_rig.py", ["--out", rig, "--pose", "A"], rig.with_suffix(".make.json"))
        base = pipeline.add_asset(rig, "Molde", step)
        files["https://assets.meshy.test/modelo.glb"] = (store.folder("asset", base["id"]) / base["preview"]).read_bytes()
        asset = pipeline.approve_meshy(second["id"], polycount=20000, log=step)
        kind, body = posts[-1]
        expect(kind == "image-to-3d" and (body["input_task_id"], body["pose_mode"], body["should_remesh"], body["target_polycount"], body["target_formats"]) == (second["image_task"], "a-pose", True, 20000, ["glb"]), f"o modelo não foi pedido a partir da imagem aprovada: {posts[-1]}")
        done = meshy.get(second["id"])
        expect((done["status"], done["asset_id"]) == (meshy.READY, asset["id"]) and (meshy.REQUESTS / second["id"] / "modelo.glb").is_file(), f"o pedido não ficou pronto com o projeto dele: {done['status']}, {done['asset_id']}")
        expect(asset["name"] == "Zumbi Teste" and asset["verdict"] and asset["filename"] == "zumbi-teste.glb" and asset["meshy"]["request"] == second["id"], f"o projeto não nasceu com o nome e o laudo: {asset['name']}, {asset['verdict']}, {asset['filename']}")
        expect(sorted(a["name"] for a in store.list_all("asset")) == ["Molde", "Zumbi Teste"], "o projeto novo não está entre os projetos")
        expect(refused(lambda: pipeline.approve_meshy(second["id"], log=step)) and refused(lambda: meshy.claim(second["id"])) and len(posts) == 3, "aprovar de novo pediu outro modelo")

        # 5) O Meshy desiste da tarefa: o pedido volta a aguardar aprovação e a próxima tentativa pede outra.
        third = meshy.request_image("A zombie boy, full body", "Zumbi Dois", pose="t-pose", log=step)
        plan[f"image-to-3d-{len(posts) + 1}"] = ["IN_PROGRESS", "FAILED"]
        expect(refused(lambda: pipeline.approve_meshy(third["id"], log=step)), "não avisou que o Meshy desistiu do modelo")
        back = meshy.get(third["id"])
        expect((back["status"], back.get("model_task")) == (meshy.WAITING, None) and "não serve" in (back["error"] or ""), f"depois da falha o pedido não voltou a aguardar aprovação: {back['status']}, {back.get('model_task')}, {back['error']}")

        # 6) Só a rede cai: a mesma tarefa é retomada, sem pedir (nem pagar) outra.
        task = f"image-to-3d-{len(posts) + 1}"
        plan[task] = ["IN_PROGRESS", "REDE"]
        expect(refused(lambda: pipeline.approve_meshy(third["id"], log=step)), "não avisou da rede fora do ar")
        kept = meshy.get(third["id"])
        expect((kept["status"], kept.get("model_task")) == (meshy.WAITING, task), f"com a rede fora, a tarefa em andamento não ficou guardada: {kept['status']}, {kept.get('model_task')}")
        before = len(posts)
        plan[task] = ["SUCCEEDED"]
        again = pipeline.approve_meshy(third["id"], log=step)
        expect(len(posts) == before and posts[-1][1]["pose_mode"] == "t-pose" and meshy.get(third["id"])["asset_id"] == again["id"], "ao retomar, pediu outro modelo em vez de esperar o que já estava sendo feito")

        # 7) Tirar da lista não mexe no projeto.
        meshy.delete(second["id"])
        expect([r["id"] for r in meshy.list_requests()] == [third["id"]] and store.get("asset", asset["id"])["name"] == "Zumbi Teste", "tirar o pedido da lista levou o projeto junto")
    finally:
        meshy._http, meshy.KEY_FILE, meshy.time.sleep = real
        shutil.rmtree(work, ignore_errors=True)
    print(("FALHA " + "; ".join(problems)) if problems else "ok    Meshy: primeiro a imagem, o modelo só depois de aprovada, e o modelo vira projeto")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
