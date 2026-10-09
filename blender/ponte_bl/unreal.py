"""O personagem no esqueleto do Mannequin da Unreal 5 (SK_Mannequin, o do Manny e da Quinn).

O personagem ganha outra armature, com os nomes, a hierarquia e os eixos dos ossos do
Mannequin: ``root`` no chao, ``pelvis``, ``spine_01`` a ``spine_05``, ``upperarm_l``... As
juntas ficam onde ja estavam no personagem; o que muda e o nome de cada osso e para onde
apontam os eixos dele. Nada e recalculado: cada osso novo anda preso ao osso de onde veio,
entao a malha deforma igual e cada animacao e a mesma, quadro a quadro.

    R_novo = C @ R_mannequin            (descanso)
    W_novo(t) = D(t) @ W_novo           (pose; D e quanto o osso de origem saiu do descanso)

C e a correcao de descanso do retarget (``rigmap.build_plan``): bracos e pernas giram para a
direcao do membro do personagem, o resto herda. E o que deixa uma animacao do Mannequin servir
no personagem, e o contrario, apesar da pose de descanso diferente (A ou T).

Os ossos do Mannequin sem par no personagem (os da coluna e do pescoco que sobram, os
metacarpos) entram no lugar, sem peso, para a hierarquia bater; os de IK copiam o pe e a mao.
Os de torcao e de correcao ficam de fora. Os do personagem sem par no Mannequin (cabelo,
roupa) continuam, com o nome que tinham; os que nao tem peso nem nada preso saem.

Referencia: ``ue5_mannequin.json``, tirado da Unreal 5.8 (o espaco esta descrito la dentro).

Duas coisas que a Unreal cobra do arquivo, conferidas importando na 5.8 (``export``):

- centimetros de verdade. A escala do objeto da armature vira escala do osso raiz (``root`` com
  100), entao a armature nova e a malha sao feitas em centimetros, sem escala em objeto nenhum;
- a pose de vinculacao exata. O Blender grava as matrizes dela a partir de numeros de 32 bits, e
  nessa escala o ruido passa da tolerancia do SDK do FBX: a Unreal descarta a pose de descanso e
  usa o primeiro quadro da primeira animacao no lugar. ``clean_bind_pose`` regrava as matrizes
  exatamente ortonormais.
"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix

from . import rigmap
from . import scene as scene_io
from .retarget import _unit, _write_fcurve, fix_continuity, mat_to_quat, quat_to_mat, shortest_arc, yaw_between

REFERENCE = Path(__file__).with_name("ue5_mannequin.json")
# Unreal: mao esquerda, frente em +Y. Blender: mao direita, frente em -Y. Espelha o Y.
MIRROR = np.diag([1.0, -1.0, 1.0])
SPINE = ("spine_01", "spine_02", "spine_03", "spine_04", "spine_05")
NECK = ("neck_01", "neck_02")
PARTS = {"shoulder": "clavicle", "arm": "upperarm", "forearm": "lowerarm", "hand": "hand", "upleg": "thigh", "leg": "calf", "foot": "foot", "toe": "ball"}
LIMBS = ("clavicle", "upperarm", "lowerarm", "hand", "thigh", "calf", "foot")
# Ossos de IK do Mannequin e o osso que cada um copia (None: fica na raiz).
IK = {"ik_foot_root": None, "ik_foot_l": "foot_l", "ik_foot_r": "foot_r", "ik_hand_root": None, "ik_hand_gun": "hand_r", "ik_hand_l": "hand_l", "ik_hand_r": "hand_r"}
UNIT = 100.0  # centimetros por metro


def load_reference() -> dict[str, dict]:
    """Os ossos do Mannequin no espaco do Blender (metros): ``{nome: {parent, head, rot}}``."""
    out = {}
    for bone in json.loads(REFERENCE.read_text(encoding="utf-8"))["bones"]:
        x, y, z, w = bone["quat"]
        out[bone["name"]] = {"parent": bone["parent"], "head": MIRROR @ np.array(bone["loc"]) / 100.0, "rot": MIRROR @ quat_to_mat((w, x, y, z)) @ MIRROR}
    return out


def ue_name(slot: str) -> str:
    """Nome do osso do Mannequin que faz o papel de um slot (``l_index2`` -> ``index_02_l``)."""
    if slot == "hips":
        return "pelvis"
    if slot == "head":
        return "head"
    side, part = slot.split("_", 1)
    if part in PARTS:
        return f"{PARTS[part]}_{side}"
    return f"{part[:-1]}_0{part[-1]}_{side}"


def _fractions(points: list[np.ndarray]) -> list[float]:
    """Onde cada ponto fica ao longo do caminho, de 0 (o primeiro) a 1 (o ultimo)."""
    steps = [float(np.linalg.norm(b - a)) for a, b in zip(points, points[1:])]
    total = sum(steps) or 1.0
    return [sum(steps[:i]) / total for i in range(len(points))]


def match_chain(char_at: list[float], ref_at: list[float], names: tuple[str, ...], pin_last: bool) -> list[str]:
    """A que osso do Mannequin vai cada osso de uma cadeia do personagem: o de altura mais
    parecida, sem trocar a ordem. ``pin_last`` prende o ultimo ao ultimo (o peito e sempre
    ``spine_05``, de onde saem os bracos)."""
    n = len(char_at)
    if n == 0:
        return []
    options = [c for c in combinations(range(len(names)), n) if not pin_last or c[-1] == len(names) - 1]
    best = min(options, key=lambda c: sum((char_at[i] - ref_at[j]) ** 2 for i, j in enumerate(c)))
    return [names[j] for j in best]


def _rigid(matrix: np.ndarray) -> np.ndarray:
    """A mesma matriz sem a escala (a armature do Mixamo vem com 0,01)."""
    out = np.eye(4)
    out[:3, :3] = matrix[:3, :3] / np.linalg.norm(matrix[:3, :3], axis=0)
    out[:3, 3] = matrix[:3, 3]
    return out


def _frame(head: np.ndarray, rot: np.ndarray) -> np.ndarray:
    out = np.eye(4)
    out[:3, :3] = rot
    out[:3, 3] = head
    return out


def plan_skeleton(bones: list[dict], used: set[str], override: dict | None = None) -> dict:
    """Decide o esqueleto novo. Nao usa bpy.

    ``bones``: [{name, parent, matrix}] do personagem, com ``matrix`` 4x4 de descanso no mundo.
    ``used``: ossos que tem peso em alguma malha ou algo preso neles.
    Devolve ``table`` ([{name, parent, matrix, source, owner}], pai antes de filho) e um resumo.
    ``source`` e o osso do personagem que o novo segue; ``owner`` diz se ele fica com os pesos
    desse osso (os que entram so para completar a hierarquia seguem o pai e nao tem peso).
    """
    ref = load_reference()
    parents = {b["name"]: b["parent"] for b in bones}
    rest = {b["name"]: _rigid(np.asarray(b["matrix"], dtype=np.float64)) for b in bones}
    head = {name: m[:3, 3] for name, m in rest.items()}
    mapping = rigmap.build_mapping([(b["name"], b["parent"]) for b in bones], override)
    if not mapping["retargetable"]:
        raise RuntimeError("O esqueleto do personagem não tem todos os ossos de um humanoide, então não dá para levá-lo ao da Unreal 5. Faltam: " + ", ".join(rigmap.slot_label(s) if s != "torso" else "tronco" for s in mapping["missing_required"]))
    slots, torso, neck = mapping["slots"], mapping["torso"], mapping["neck"]
    if len(torso) > len(SPINE) or len(neck) > len(NECK):
        raise RuntimeError(f"O personagem tem {len(torso)} osso(s) na coluna e {len(neck)} no pescoço; o esqueleto da Unreal 5 tem {len(SPINE)} e {len(NECK)}.")

    # --- Que osso do Mannequin cada osso do personagem vira -----------------------
    ue_of = {bone: ue_name(slot) for slot, bone in slots.items()}
    for slot, bone in slots.items():  # dedo com falange faltando no meio nao encaixa na cadeia
        part = slot.split("_", 1)[-1]
        if part[:-1] in rigmap.FINGERS and any(f"{slot[:-1]}{i}" not in slots for i in range(1, int(part[-1]))):
            del ue_of[bone]
    chain = [head[slots["hips"]]] + [head[b] for b in torso]
    ref_chain = [ref["pelvis"]["head"]] + [ref[n]["head"] for n in SPINE]
    ue_of.update(zip(torso, match_chain(_fractions(chain)[1:], _fractions(ref_chain)[1:], SPINE, pin_last=True)))
    chain = [head[torso[-1]]] + [head[b] for b in neck] + [head[slots["head"]]]
    ref_chain = [ref["spine_05"]["head"]] + [ref[n]["head"] for n in NECK] + [ref["head"]["head"]]
    ue_of.update(zip(neck, match_chain(_fractions(chain)[1:-1], _fractions(ref_chain)[1:-1], NECK, pin_last=False)))
    src_of = {ue: bone for bone, ue in ue_of.items()}

    # --- Correcao de descanso, como no retarget ------------------------------------
    up = np.array([0.0, 0.0, 1.0])
    facing, facing_angle = yaw_between(ref["thigh_l"]["head"] - ref["thigh_r"]["head"], head[slots["l_upleg"]] - head[slots["r_upleg"]], up)
    swing: dict[str, np.ndarray] = {}
    for item in rigmap.build_plan(mapping):
        bone = item["bone"]
        if item["mode"] == "root":
            swing[bone] = facing
            continue
        base = swing[item["base"]]
        if item["mode"] == "inherit" or bone not in ue_of or item["aim_bone"] not in ue_of:
            swing[bone] = base
            continue
        d_ref = base @ _unit(ref[ue_of[item["aim_bone"]]]["head"] - ref[ue_of[bone]]["head"])
        swing[bone] = shortest_arc(d_ref, _unit(head[item["aim_bone"]] - head[bone])) @ base

    # --- Os ossos do Mannequin que entram -------------------------------------------
    wanted = {"root", "pelvis", "head", *SPINE, *NECK, *IK, *src_of} | {f"{part}_{s}" for part in LIMBS for s in "lr"}
    wanted |= {f"{name.split('_')[0]}_metacarpal_{name[-1]}" for name in src_of if name.split("_")[0] in ("index", "middle", "ring", "pinky") and "_01_" in name}
    table: list[dict] = []
    row_of: dict[str, dict] = {}
    inserted: list[str] = []

    def add(name: str, parent: str | None, matrix: np.ndarray, source: str | None, owner: bool) -> None:
        row_of[name] = {"name": name, "parent": parent, "matrix": matrix, "source": source, "owner": owner}
        table.append(row_of[name])

    def between(name: str) -> np.ndarray:
        """Posicao de um osso que o personagem nao tem: entre os vizinhos que ele tem, na
        proporcao em que o Mannequin o poe."""
        side = name[-1]
        if name in SPINE:
            path = ["pelvis", *SPINE]
        elif name in NECK:
            path = ["spine_05", *NECK, "head"]
        elif name.startswith("clavicle"):
            path = ["spine_05", name, f"upperarm_{side}"]
        else:  # metacarpo
            path = [f"hand_{side}", name, f"{name.split('_')[0]}_01_{side}"]
        i = path.index(name)
        low = max(j for j in range(i) if path[j] in src_of)
        high = min(j for j in range(i + 1, len(path)) if path[j] in src_of)
        at = _fractions([ref[n]["head"] for n in path[low : high + 1]])[i - low]
        return head[src_of[path[low]]] + (head[src_of[path[high]]] - head[src_of[path[low]]]) * at

    for name, bone in ref.items():  # a referencia ja vem com o pai antes do filho
        if name not in wanted:
            continue
        if name == "root" or IK.get(name, "") is None:
            add(name, bone["parent"], np.eye(4), None, False)
        elif name in IK:
            add(name, bone["parent"], row_of[IK[name]]["matrix"].copy(), row_of[IK[name]]["source"], False)
        elif name in src_of:
            source = src_of[name]
            add(name, bone["parent"], _frame(head[source], swing[source] @ bone["rot"]), source, True)
        else:  # completa a hierarquia: segue o pai
            source = row_of[bone["parent"]]["source"]
            add(name, bone["parent"], _frame(between(name), swing.get(source, facing) @ bone["rot"]), source, False)
            inserted.append(name)

    # --- Os ossos do personagem que nao existem no Mannequin ------------------------
    depth = {}
    for b in bones:
        depth[b["name"]] = 0 if b["parent"] is None else depth.get(b["parent"], 0) + 1
    keep = set()
    for name in used:
        while name is not None and name not in ue_of and name not in keep:
            keep.add(name)
            name = parents[name]
    new_name = dict(ue_of)
    extra = []
    for b in sorted(bones, key=lambda b: depth[b["name"]]):
        name = b["name"]
        if name not in keep:
            continue
        up_name = parents[name]
        while up_name is not None and up_name not in new_name:
            up_name = parents[up_name]
        new_name[name] = name if name not in row_of else name + "_extra"
        add(new_name[name], new_name[up_name] if up_name else "root", rest[name], name, True)
        extra.append(name)

    return {
        "table": table,
        "renamed": new_name,
        "summary": {
            "bones": len(table),
            "mapped": len(src_of),
            "inserted": inserted,
            "extra": extra,
            "dropped": sorted(set(parents) - set(new_name)),
            "facing_deg": round(float(np.degrees(facing_angle)), 2),
        },
    }


def _source_clips(arm_obj) -> list[tuple]:
    """(nome, action, slot) de cada faixa NLA: e assim que o resultado guarda os clipes."""
    anim = arm_obj.animation_data
    clips = []
    for track in anim.nla_tracks if anim else []:
        for strip in track.strips:
            if strip.action is not None:
                clips.append((strip.name, strip.action, strip.action_slot))
    return clips


def _play(obj, action, slot) -> None:
    anim = obj.animation_data
    for track in anim.nla_tracks:
        track.mute = True
    anim.action = action
    if slot is not None or action.slots:
        anim.action_slot = slot if slot is not None else action.slots[0]


def _deformed(meshes: list) -> np.ndarray:
    """Os vertices de todas as malhas, deformados, no mundo."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    parts = []
    for obj in meshes:
        ev = obj.evaluated_get(depsgraph)
        co = np.empty(len(ev.data.vertices) * 3)
        ev.data.vertices.foreach_get("co", co)
        world = np.array(ev.matrix_world)
        parts.append(co.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3])
    return np.concatenate(parts) if parts else np.zeros((0, 3))


def convert(arm_obj, meshes: list, override: dict | None = None) -> dict:
    """Troca a armature do personagem pela do Mannequin e regrava os clipes nela.

    A cena precisa estar como o resultado a deixa: os clipes em faixas NLA de ``arm_obj``.
    Ela sai em centimetros: a armature nova, as malhas e o que estava preso em osso ficam 100
    vezes maiores, para o FBX nao levar escala em objeto. Devolve o resumo, com ``check``:
    quanto a malha deformada e as juntas mudaram (deveria ser nada).
    """
    scene = bpy.context.scene
    view = bpy.context.view_layer
    world = np.array(arm_obj.matrix_world)
    src = arm_obj.data
    clips = _source_clips(arm_obj)
    if not clips:
        raise RuntimeError("O personagem não tem animação para levar ao esqueleto da Unreal 5.")

    used = {obj.parent_bone for obj in scene.objects if obj.parent == arm_obj and obj.parent_type == "BONE"}
    for obj in meshes:
        names = [g.name for g in obj.vertex_groups]
        for v in obj.data.vertices:
            for g in v.groups:
                if g.weight > 0.0:
                    used.add(names[g.group])
    used &= {b.name for b in src.bones}
    plan = plan_skeleton([{"name": b.name, "parent": b.parent.name if b.parent else None, "matrix": world @ np.array(b.matrix_local)} for b in src.bones], used, override)
    table, renamed = plan["table"], plan["renamed"]

    # Antes de mexer: como a malha fica em tres quadros do primeiro clipe, para conferir no fim.
    name, action, slot = clips[0]
    start, end = (int(round(v)) for v in action.frame_range)
    probes = sorted({start, (start + end) // 2, end})
    _play(arm_obj, action, slot)
    before = []
    for frame in probes:
        scene.frame_set(frame)
        before.append(_deformed(meshes))

    # --- A armature nova, em descanso ------------------------------------------------
    arm_obj.name = arm_obj.name + "_origem"
    data = bpy.data.armatures.new("Armature")
    new_obj = bpy.data.objects.new("Armature", data)
    (arm_obj.users_collection[0] if arm_obj.users_collection else scene.collection).objects.link(new_obj)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    view.objects.active = new_obj
    length = UNIT * max(0.02, 0.03 * float(np.ptp([row["matrix"][2, 3] for row in table])))
    bpy.ops.object.mode_set(mode="EDIT")
    for row in table:
        eb = data.edit_bones.new(row["name"])
        eb.head, eb.tail = (0.0, 0.0, 0.0), (0.0, length, 0.0)
        eb.matrix = Matrix(_frame(row["matrix"][:3, 3] * UNIT, row["matrix"][:3, :3]).tolist())
        eb.length = length
        if row["parent"]:
            eb.parent = data.edit_bones[row["parent"]]
        eb.use_connect = False
        eb.use_deform = row["owner"]
    bpy.ops.object.mode_set(mode="OBJECT")
    # O descanso que o Blender guardou, de volta em metros (no mundo), para a conta dos clipes.
    new_rest = {}
    for row in table:
        local = np.array(data.bones[row["name"]].matrix_local)
        new_rest[row["name"]] = _frame(local[:3, 3] / UNIT, local[:3, :3])

    # --- Malhas e o que estava preso em osso passam para ela, com as duas em descanso ---
    src.pose_position = data.pose_position = "REST"
    view.update()
    grow = Matrix.Scale(UNIT, 4)
    loose = {obj: grow @ obj.matrix_world for obj in meshes if obj.parent != arm_obj}
    for obj in list(scene.objects):
        for mod in obj.modifiers if obj.type == "MESH" else ():
            if mod.type == "ARMATURE" and mod.object == arm_obj:
                mod.object = new_obj
        if obj.parent != arm_obj:
            continue
        keep_world = grow @ obj.matrix_world
        kind = obj.parent_type
        bone = renamed.get(obj.parent_bone) if kind == "BONE" else None
        obj.parent = new_obj
        obj.parent_type = "BONE" if bone else "ARMATURE" if kind == "ARMATURE" else "OBJECT"
        if bone:
            obj.parent_bone = bone
        view.update()
        obj.matrix_world = keep_world
    for obj, world_cm in loose.items():  # malha solta, presa so pelo modificador
        obj.matrix_world = world_cm
    view.update()
    for obj in meshes:
        if any(mod.type == "ARMATURE" and mod.object == new_obj for mod in obj.modifiers):
            # A escala vai para os vertices, e o objeto da malha sai do FBX sem escala nenhuma.
            if obj.data.users > 1:
                obj.data = obj.data.copy()
            obj.data.transform(obj.matrix_world, shape_keys=True)
            obj.matrix_world = Matrix.Identity(4)
        groups = [(g, renamed[g.name]) for g in obj.vertex_groups if g.name in renamed]
        for i, (group, _new) in enumerate(groups):  # em dois tempos: um nome novo pode ser o velho de outro
            group.name = f"__ponte_{i}"
        for group, new in groups:
            group.name = new
    src.pose_position = data.pose_position = "POSE"
    view.update()

    # --- Cada clipe, regravado: o osso novo vai aonde foi o osso de origem -----------
    rows = {row["name"]: row for row in table}
    sources = sorted({row["source"] for row in table if row["source"]})
    index = {name: i for i, name in enumerate(sources)}
    rest_inv = np.stack([np.linalg.inv(world @ np.array(src.bones[name].matrix_local)) for name in sources])
    new_obj.animation_data_create()
    done = []
    worst_joint = 0.0
    for name, action, slot in clips:
        _play(arm_obj, action, slot)
        start, end = (int(round(v)) for v in action.frame_range)
        frames = np.arange(start, end + 1, dtype=np.float64)
        posed = np.empty((len(frames), len(sources), 4, 4))
        for i, frame in enumerate(range(start, end + 1)):
            scene.frame_set(frame)
            ev = arm_obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            for k, bone in enumerate(sources):
                posed[i, k] = ev.pose.bones[bone].matrix
        delta = (world @ posed) @ rest_inv  # (quadros, ossos, 4, 4): quanto cada osso saiu do descanso, no mundo
        delta_inv = np.linalg.inv(delta)
        new_action = bpy.data.actions.new("__ponte_" + name)
        new_obj.animation_data.action = new_action
        for row in table:
            source, above = row["source"], rows[row["parent"]]["source"] if row["parent"] else None
            if source is None or above == source:
                continue  # parado em relacao ao pai
            rest = new_rest[row["name"]]
            basis = np.linalg.inv(rest) @ (delta[:, index[source]] if above is None else delta_inv[:, index[above]] @ delta[:, index[source]]) @ rest
            pb = new_obj.pose.bones[row["name"]]
            pb.rotation_mode = "QUATERNION"
            quat = fix_continuity(mat_to_quat(basis[:, :3, :3] / np.linalg.norm(basis[:, :3, :3], axis=1, keepdims=True)))
            for i in range(4):
                _write_fcurve(new_action, new_obj, pb.path_from_id("rotation_quaternion"), i, frames, quat[:, i], row["name"])
            if np.abs(basis[:, :3, 3]).max() > 1e-5:
                for i in range(3):
                    _write_fcurve(new_action, new_obj, pb.path_from_id("location"), i, frames, basis[:, i, 3] * UNIT, row["name"])
        if new_obj.animation_data.action_slot is None and new_action.slots:
            new_obj.animation_data.action_slot = new_action.slots[0]
        # As juntas do primeiro e do ultimo quadro tem de cair onde estavam.
        for i in (0, len(frames) - 1):
            scene.frame_set(int(frames[i]))
            ev = new_obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            for row in table:
                if row["owner"]:
                    want = (delta[i, index[row["source"]]] @ row["matrix"])[:3, 3]
                    worst_joint = max(worst_joint, float(np.linalg.norm(np.array(ev.pose.bones[row["name"]].matrix)[:3, 3] / UNIT - want)))
        new_obj.animation_data.action = None  # parada, a armature nova nao faz a malha ser recalculada a cada quadro
        done.append((name, new_action, start, end))

    # A malha, nos mesmos tres quadros do comeco.
    new_obj.animation_data.action = done[0][1]
    new_obj.animation_data.action_slot = done[0][1].slots[0]
    worst_vertex = 0.0
    for frame, old in zip(probes, before):
        scene.frame_set(frame)
        now = _deformed(meshes)
        if len(now):
            worst_vertex = max(worst_vertex, float(np.linalg.norm(now / UNIT - old, axis=1).max()))

    # --- Sai a armature de origem; os clipes novos viram as faixas NLA ----------------
    old_actions = [action for _name, action, _slot in clips]
    bpy.data.objects.remove(arm_obj)
    for action in old_actions:
        if action.users == 0:
            bpy.data.actions.remove(action)
    anim = new_obj.animation_data
    anim.action = None
    for pb in new_obj.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    for name, new_action, start, _end in done:
        new_action.name = name
        track = anim.nla_tracks.new()
        track.name = name
        # A Unreal chama cada animacao de <arquivo><tomada>, sem nada no meio: o "_" separa.
        strip = track.strips.new("_" + name, start, new_action)
        if new_action.slots:
            strip.action_slot = new_action.slots[0]
    scene.frame_set(0)
    return {
        **plan["summary"],
        "armature": new_obj.name,
        "clips": [name for name, *_ in done],
        "check": {"vertex_error_cm": round(worst_vertex * 100, 4), "joint_error_cm": round(worst_joint * 100, 4)},
    }


def export(path: Path) -> dict:
    """Grava o FBX para a Unreal 5. A cena ja esta em centimetros (``convert``)."""
    # global_scale desfaz os x100 que o exportador aplica para ir de metro a centimetro.
    scene_io.export_fbx(path, nla_strips=True, global_scale=1.0 / UNIT, mesh_smooth_type="FACE")
    return clean_bind_pose(path)


_FBX_ADD = {
    "B": "add_bool", "C": "add_char", "Z": "add_int8", "Y": "add_int16", "I": "add_int32", "L": "add_int64", "F": "add_float32", "D": "add_float64",
    "R": "add_bytes", "S": "add_string", "i": "add_int32_array", "l": "add_int64_array", "f": "add_float32_array", "d": "add_float64_array",
    "b": "add_bool_array", "c": "add_byte_array",
}


def clean_bind_pose(path: Path) -> dict:
    """Regrava o FBX com a pose de vinculacao exata: a matriz de cada osso ortonormal, e as dos
    clusters refeitas a partir dela. O resto do arquivo volta como estava.

    Usa o leitor e o gravador de FBX do proprio Blender. Devolve quantos ossos e clusters mudou.
    """
    from io_scene_fbx import encode_bin, parse_fbx

    root, version = parse_fbx.parse(str(path))
    objects = next(e for e in root.elems if e.id == b"Objects")
    kinds = {e.props[0]: (e.id, e.props[2] if len(e.props) > 2 else b"") for e in objects.elems}
    up: dict = {}
    down: dict = {}
    for link in next(e for e in root.elems if e.id == b"Connections").elems:
        if link.props[0] == b"OO":
            up.setdefault(link.props[1], []).append(link.props[2])
            down.setdefault(link.props[2], []).append(link.props[1])

    def child(elem, name: bytes):
        return next((e for e in elem.elems if e.id == name), None)

    def matrix(values) -> np.ndarray:
        return np.array(values, dtype=np.float64).reshape(4, 4).T  # o FBX guarda por colunas

    def flat(m: np.ndarray) -> list[float]:
        return m.T.reshape(-1).tolist()

    bones = {uid for uid, kind in kinds.items() if kind == (b"Model", b"LimbNode")}
    pose: dict = {}
    for elem in objects.elems:
        if elem.id != b"Pose":
            continue
        for node in (e for e in elem.elems if e.id == b"PoseNode"):
            uid = child(node, b"Node").props[0]
            m = matrix(child(node, b"Matrix").props[0])
            if uid in bones:  # a rotacao mais proxima da que esta la (decomposicao polar)
                u, sizes, vt = np.linalg.svd(m[:3, :3])
                size = float(sizes.mean())
                m[:3, :3] = (u @ vt) * (1.0 if abs(size - 1.0) < 1e-4 else size)  # escala de verdade fica; ruido, nao
            pose[uid] = m

    def mesh_of(cluster) -> np.ndarray | None:
        for skin in up.get(cluster, []):
            for geometry in up.get(skin, []) if kinds.get(skin, (b"", b""))[1] == b"Skin" else []:
                for model in up.get(geometry, []):
                    if model in pose:
                        return pose[model]
        return None

    clusters: dict = {}
    for elem in objects.elems:
        if elem.id == b"Deformer" and elem.props[2] == b"Cluster" and child(elem, b"TransformLink") is not None:
            bone = next((b for b in down.get(elem.props[0], []) if b in bones and b in pose), None)
            mesh = mesh_of(elem.props[0])
            if bone is not None and mesh is not None:
                clusters[elem.props[0]] = {b"TransformLink": flat(pose[bone]), b"Transform": flat(np.linalg.inv(pose[bone]) @ mesh)}

    def rebuild(parent, elem, cluster=None, pose_node=None):
        out = encode_bin.FBXElem(elem.id)
        if parent is not None:
            parent.elems.append(out)
        if elem.id == b"PoseNode":
            pose_node = child(elem, b"Node").props[0]
        elif elem.id == b"Deformer" and elem.props and elem.props[0] in clusters:
            cluster = clusters[elem.props[0]]
        for value, kind in zip(elem.props, elem.props_type):
            if kind == ord("d") and cluster is not None and elem.id in cluster:
                value = cluster[elem.id]
            elif kind == ord("d") and pose_node in bones and elem.id == b"Matrix":
                value = flat(pose[pose_node])
            getattr(out, _FBX_ADD[chr(kind)])(value)
        for sub in elem.elems:
            rebuild(out, sub, cluster, pose_node)
        return out

    with encode_bin.FBXElem.enable_multithreading_cm():
        new_root = encode_bin.FBXElem(b"")
        for elem in root.elems:
            rebuild(new_root, elem)
    encode_bin.write(str(path), new_root, version)
    return {"bones": len(bones & set(pose)), "clusters": len(clusters)}
