"""Retarget de um BVH do Kimodo (SOMA 77) para uma armature do Blender.

Metodo: transferencia de rotacao global. Num BVH a rotacao global de cada junta
ja e o delta em relacao ao descanso, em espaco de mundo. Para cada osso mapeado:

    R_pose(t) = D(t) @ C @ R_rest

onde D e o delta da fonte levado para o espaco da armature e C e a correcao de
descanso do osso (ver ``rigmap.build_plan``). Como o alvo recebe orientacoes
absolutas, juntas da fonte sem par no alvo (ex.: Neck2) nao se perdem: a rotacao
delas ja esta embutida na global do filho. Ossos do alvo sem par ficam em
repouso relativo ao pai.
"""

from __future__ import annotations

import bpy
import numpy as np

from . import rigmap
from .bvh import BvhMotion

# BVH do Kimodo: Y para cima, +Z para frente, +X a esquerda do personagem.
# Blender: Z para cima, personagem de frente olha para -Y.
SRC_TO_WORLD = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])

# No SOMA o tornozelo fica a ~7,0 cm do chao com o pe plantado, para 93,8 cm de
# quadril a tornozelo (medido numa caminhada do Kimodo-SOMA-RP-v1.1).
SOMA_ANKLE_FLOOR_RATIO = 7.0 / 93.8


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    x, y, z = _unit(axis)
    k = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return np.eye(3) + np.sin(angle) * k + (1.0 - np.cos(angle)) * (k @ k)


def shortest_arc(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Menor rotacao R tal que R @ a fica paralelo a b."""
    a, b = _unit(a), _unit(b)
    c = float(np.clip(a @ b, -1.0, 1.0))
    axis = np.cross(a, b)
    if np.linalg.norm(axis) < 1e-9:
        if c > 0:
            return np.eye(3)
        seed = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        return _axis_angle(np.cross(a, seed), np.pi)
    return _axis_angle(axis, np.arccos(c))


def yaw_between(a: np.ndarray, b: np.ndarray, up: np.ndarray) -> tuple[np.ndarray, float]:
    """Rotacao em torno de ``up`` que leva a projecao horizontal de a para a de b."""
    up = _unit(up)
    a = _unit(a - (a @ up) * up)
    b = _unit(b - (b @ up) * up)
    angle = float(np.arctan2(np.cross(a, b) @ up, a @ b))
    return _axis_angle(up, angle), angle


def mat_to_quat(rot: np.ndarray) -> np.ndarray:
    """(..., 3, 3) -> (..., 4) em ordem w, x, y, z (metodo de Shepperd)."""
    m = rot.reshape(-1, 3, 3)
    t = np.stack(
        [
            1 + m[:, 0, 0] + m[:, 1, 1] + m[:, 2, 2],
            1 + m[:, 0, 0] - m[:, 1, 1] - m[:, 2, 2],
            1 - m[:, 0, 0] + m[:, 1, 1] - m[:, 2, 2],
            1 - m[:, 0, 0] - m[:, 1, 1] + m[:, 2, 2],
        ],
        axis=1,
    )
    case = np.argmax(t, axis=1)
    q = np.empty((m.shape[0], 4))
    for c in range(4):
        idx = np.nonzero(case == c)[0]
        if not len(idx):
            continue
        mm = m[idx]
        s = 2.0 * np.sqrt(np.maximum(t[idx, c], 1e-12))
        if c == 0:
            comp = [s / 4, (mm[:, 2, 1] - mm[:, 1, 2]) / s, (mm[:, 0, 2] - mm[:, 2, 0]) / s, (mm[:, 1, 0] - mm[:, 0, 1]) / s]
        elif c == 1:
            comp = [(mm[:, 2, 1] - mm[:, 1, 2]) / s, s / 4, (mm[:, 0, 1] + mm[:, 1, 0]) / s, (mm[:, 0, 2] + mm[:, 2, 0]) / s]
        elif c == 2:
            comp = [(mm[:, 0, 2] - mm[:, 2, 0]) / s, (mm[:, 0, 1] + mm[:, 1, 0]) / s, s / 4, (mm[:, 1, 2] + mm[:, 2, 1]) / s]
        else:
            comp = [(mm[:, 1, 0] - mm[:, 0, 1]) / s, (mm[:, 0, 2] + mm[:, 2, 0]) / s, (mm[:, 1, 2] + mm[:, 2, 1]) / s, s / 4]
        q[idx] = np.stack(comp, axis=1)
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    return q.reshape(rot.shape[:-2] + (4,))


def quat_to_mat(quat) -> np.ndarray:
    """Quaternion (w, x, y, z) -> matriz 3x3."""
    w, x, y, z = np.asarray(quat, dtype=np.float64) / np.linalg.norm(quat)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def fix_continuity(q: np.ndarray) -> np.ndarray:
    """Evita a troca de sinal q/-q entre frames vizinhos (quebraria a interpolacao)."""
    sign = np.sign(np.einsum("ti,ti->t", q[1:], q[:-1]))
    sign[sign == 0] = 1.0
    flip = np.concatenate([[1.0], np.cumprod(sign)])
    return q * flip[:, None]


def _angle_deg(rot: np.ndarray) -> np.ndarray:
    tr = np.trace(rot, axis1=-2, axis2=-1)
    return np.degrees(np.arccos(np.clip((tr - 1.0) / 2.0, -1.0, 1.0)))


def _smooth(x: np.ndarray, sigma: float) -> np.ndarray:
    """Passa-baixa gaussiano. A borda e espelhada com sinal trocado, o que preserva
    tendencia linear: uma caminhada em velocidade constante sai inteira no resultado."""
    radius = min(int(3 * sigma), len(x) - 1)
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(x, ((radius, radius), (0, 0)), mode="reflect", reflect_type="odd")
    return np.stack([np.convolve(padded[:, i], kernel, mode="valid") for i in range(x.shape[1])], axis=1)


def _write_fcurve(action, obj, path: str, index: int, frames: np.ndarray, values: np.ndarray, group: str) -> None:
    try:
        fc = action.fcurve_ensure_for_datablock(obj, path, index=index, group_name=group)
    except TypeError:
        fc = action.fcurve_ensure_for_datablock(obj, path, index=index)
    n = len(frames)
    fc.keyframe_points.add(n)
    co = np.empty(2 * n)
    co[0::2] = frames
    co[1::2] = values
    fc.keyframe_points.foreach_set("co", co)
    linear = bpy.types.Keyframe.bl_rna.properties["interpolation"].enum_items["LINEAR"].value
    fc.keyframe_points.foreach_set("interpolation", np.full(n, linear, dtype=np.int32))
    fc.update()


def retarget(
    arm_obj,
    meshes: list,
    motion: BvhMotion,
    mapping: dict,
    *,
    action_name: str = "Kimodo",
    in_place: bool = False,
    frame_start: int = 0,
    adjust: dict | None = None,
) -> dict:
    """Anima ``arm_obj`` com ``motion`` e devolve as medidas do resultado.

    ``adjust`` e o ajuste de pose feito a mao: ``{osso: [w, x, y, z]}``, uma rotacao extra
    no espaco local do osso, aplicada depois da animacao e valendo no clipe inteiro.
    """
    missing = [j for j in ("Hips", "LeftLeg", "RightLeg", "LeftFoot", "RightFoot") if j not in motion.names]
    if missing:
        raise ValueError(f"O BVH não é um SOMA 77 do Kimodo (faltam juntas: {', '.join(missing)}).")

    grot, gpos = motion.fk()
    rest = motion.rest_positions()
    jidx = {n: i for i, n in enumerate(motion.names)}
    n_frames = motion.frames
    slots = mapping["slots"]
    warnings: list[str] = []

    world = np.array(arm_obj.matrix_world)
    col_scale = np.linalg.norm(world[:3, :3], axis=0)
    if col_scale.max() / col_scale.min() > 1.001:
        warnings.append("Armature com escala não uniforme: o retarget pode distorcer.")
    world_rot = world[:3, :3] / col_scale
    world_inv = np.linalg.inv(world)
    src_to_arm = world_rot.T @ SRC_TO_WORLD
    up_arm = world_rot.T @ np.array([0.0, 0.0, 1.0])

    bones = arm_obj.data.bones
    parent = {b.name: (b.parent.name if b.parent else None) for b in bones}
    rest_rot = {b.name: np.array(b.matrix_local)[:3, :3] for b in bones}
    rest_head = {b.name: np.array(b.head_local) for b in bones}
    order: list[str] = []
    stack = [b.name for b in bones if b.parent is None][::-1]
    children: dict[str, list[str]] = {}
    for b in bones:
        if b.parent:
            children.setdefault(b.parent.name, []).append(b.name)
    while stack:
        name = stack.pop()
        order.append(name)
        stack.extend(reversed(children.get(name, [])))
    loose = [b.name for b in bones if b.parent and not b.use_inherit_rotation]
    if loose:
        warnings.append(f"{len(loose)} osso(s) não herdam rotação do pai; podem sair errados: {', '.join(loose[:5])}")
    constrained = [pb.name for pb in arm_obj.pose.bones if len(pb.constraints)]
    if constrained:
        warnings.append(
            f"{len(constrained)} osso(s) têm constraints, que podem brigar com a animação: {', '.join(constrained[:5])}"
        )

    # --- Correcoes de descanso -------------------------------------------------
    plan = rigmap.build_plan(mapping)
    plan = [item for item in plan if item["joint"] in jidx]
    side_tgt = rest_head[slots["l_upleg"]] - rest_head[slots["r_upleg"]]
    side_src = src_to_arm @ (rest[jidx["LeftLeg"]] - rest[jidx["RightLeg"]])
    facing, facing_angle = yaw_between(side_tgt, side_src, up_arm)

    correction: dict[str, np.ndarray] = {}
    aligned: dict[str, float] = {}
    for item in plan:
        bone = item["bone"]
        if item["mode"] == "root":
            correction[bone] = facing
            continue
        base = correction[item["base"]]
        if item["mode"] == "inherit" or item["aim_joint"] not in jidx:
            correction[bone] = base
            continue
        d_tgt = base @ _unit(rest_head[item["aim_bone"]] - rest_head[bone])
        d_src = src_to_arm @ (rest[jidx[item["aim_joint"]]] - rest[jidx[item["joint"]]])
        fix = shortest_arc(d_tgt, d_src)
        correction[bone] = fix @ base
        aligned[bone] = float(_angle_deg(fix))

    # --- Rotacoes de pose (espaco da armature) e base local de cada osso --------
    target_pose = {
        item["bone"]: np.einsum(
            "ij,tjk,kl->til",
            src_to_arm,
            grot[:, jidx[item["joint"]]],
            src_to_arm.T @ correction[item["bone"]] @ rest_rot[item["bone"]],
        )
        for item in plan
    }
    eye = np.eye(3)
    pose: dict[str, np.ndarray] = {}
    basis: dict[str, np.ndarray] = {}
    for name in order:
        p = parent[name]
        parent_pose = pose[p] if p else np.broadcast_to(eye, (n_frames, 3, 3))
        parent_rest = rest_rot[p] if p else eye
        if name in target_pose:
            pose[name] = target_pose[name]
            basis[name] = np.einsum("ij,tkj,tkl->til", rest_rot[name].T @ parent_rest, parent_pose, pose[name])
        else:
            pose[name] = parent_pose @ (parent_rest.T @ rest_rot[name])

    # --- Translacao do quadril ---------------------------------------------------
    hips = slots["hips"]
    hips_rest_world = (world @ np.append(rest_head[hips], 1.0))[:3]
    bbox = None
    if meshes:
        from .scene import world_bbox

        bbox = world_bbox(meshes)
    if bbox is not None:
        floor_z = float(bbox[0][2])
    else:
        feet = [slots[s] for s in ("l_foot", "r_foot", "l_toe", "r_toe") if s in slots]
        floor_z = min(float((world @ np.append(rest_head[b], 1.0))[2]) for b in feet)
    hips_to_ankle = rest[jidx["Hips"], 1] - 0.5 * (rest[jidx["LeftFoot"], 1] + rest[jidx["RightFoot"], 1])
    # Uma fonte que nao e o SOMA (animacao de FBX) diz a altura do proprio quadril em pe.
    src_stand = getattr(motion, "stand_height", None) or hips_to_ankle * (1.0 + SOMA_ANKLE_FLOOR_RATIO)
    scale = (hips_rest_world[2] - floor_z) / src_stand

    travel = (gpos[:, jidx["Hips"]] @ SRC_TO_WORLD.T) * scale  # eixos do mundo, ja na escala do alvo
    if in_place:
        travel[:, :2] -= _smooth(travel[:, :2], sigma=0.5 * motion.fps)
    hips_world = np.empty((n_frames, 3))
    hips_world[:, :2] = hips_rest_world[:2] + travel[:, :2]
    hips_world[:, 2] = floor_z + travel[:, 2]
    hips_arm = hips_world @ world_inv[:3, :3].T + world_inv[:3, 3]
    hips_loc = (hips_arm - rest_head[hips]) @ rest_rot[hips]  # = R_rest^T @ delta

    # --- Ajuste de pose feito a mao -----------------------------------------------
    adjusted = []
    for name, quat in (adjust or {}).items():
        if name not in rest_rot:
            warnings.append(f"Ajuste de pose ignorado: o osso '{name}' não existe neste personagem.")
            continue
        current = basis.get(name, np.broadcast_to(eye, (n_frames, 3, 3)))
        basis[name] = current @ quat_to_mat(quat)
        adjusted.append(name)
    if adjusted:
        # As rotacoes em espaco de armature mudam do osso ajustado para baixo.
        for name in order:
            p = parent[name]
            parent_pose = pose[p] if p else np.broadcast_to(eye, (n_frames, 3, 3))
            local = (rest_rot[p].T if p else eye) @ rest_rot[name]
            pose[name] = parent_pose @ local @ basis[name] if name in basis else parent_pose @ local

    # --- Gravacao das chaves -----------------------------------------------------
    for other in list(bpy.data.actions):
        bpy.data.actions.remove(other)
    for pb in arm_obj.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    arm_obj.animation_data_clear()
    arm_obj.animation_data_create()
    action = bpy.data.actions.new(action_name)
    arm_obj.animation_data.action = action

    frames = np.arange(n_frames, dtype=np.float64) + frame_start
    for name, rot in basis.items():
        pb = arm_obj.pose.bones[name]
        pb.rotation_mode = "QUATERNION"
        quat = fix_continuity(mat_to_quat(rot))
        path = pb.path_from_id("rotation_quaternion")
        for i in range(4):
            _write_fcurve(action, arm_obj, path, i, frames, quat[:, i], name)
    loc_path = arm_obj.pose.bones[hips].path_from_id("location")
    for i in range(3):
        _write_fcurve(action, arm_obj, loc_path, i, frames, hips_loc[:, i], hips)
    if arm_obj.animation_data.action_slot is None and action.slots:
        arm_obj.animation_data.action_slot = action.slots[0]

    scene = bpy.context.scene
    scene.render.fps = int(round(motion.fps))
    scene.render.fps_base = 1.0
    scene.frame_start = frame_start
    scene.frame_end = frame_start + n_frames - 1

    # --- Medidas -----------------------------------------------------------------
    heads: dict[str, np.ndarray] = {}
    for name in order:
        p = parent[name]
        if name == hips:
            heads[name] = hips_arm
        elif p is None:
            heads[name] = np.broadcast_to(rest_head[name], (n_frames, 3))
        else:
            heads[name] = heads[p] + (pose[p] @ (rest_rot[p].T @ (rest_head[name] - rest_head[p])))

    def to_world(points: np.ndarray) -> np.ndarray:
        return points @ world[:3, :3].T + world[:3, 3]

    # Confere a conta contra o que o Blender realmente avalia, em frames amostrados.
    rot_err = pos_err = 0.0
    for t in np.unique(np.linspace(0, n_frames - 1, min(n_frames, 16)).astype(int)):
        scene.frame_set(frame_start + int(t))
        bpy.context.view_layer.update()
        for name in target_pose:
            m = np.array(arm_obj.pose.bones[name].matrix)
            actual = m[:3, :3] / np.linalg.norm(m[:3, :3], axis=0)
            rot_err = max(rot_err, float(_angle_deg(actual @ pose[name][t].T)))
            pos_err = max(pos_err, float(np.linalg.norm(to_world(m[:3, 3]) - to_world(heads[name][t]))))
    scene.frame_set(frame_start)

    feet = {}
    for side, soma in (("l", "Left"), ("r", "Right")):
        bone = slots.get(f"{side}_foot")
        if bone is None:
            continue
        src_ankle = gpos[:, jidx[f"{soma}Foot"]]
        planted_h = src_stand - hips_to_ankle  # a altura do tornozelo com o pe no chao, no esqueleto da fonte
        speed = np.linalg.norm(np.diff(src_ankle, axis=0), axis=1) * motion.fps
        contact = (src_ankle[1:, 1] < planted_h * 1.3) & (speed < 0.25 * hips_to_ankle)
        tgt_ankle = to_world(heads[bone])
        step = np.linalg.norm(np.diff(tgt_ankle[:, :2], axis=0), axis=1)
        src_step = np.linalg.norm(np.diff(src_ankle[:, [0, 2]], axis=0), axis=1) * scale
        seconds = float(contact.sum()) / motion.fps
        rest_h = float(to_world(rest_head[bone])[2] - floor_z)
        feet[side] = {
            "contact_seconds": round(seconds, 2),
            # Parado no lugar o pe desliza de proposito; a medida nao se aplica.
            "slide_cm_per_s": round(100.0 * float(step[contact].sum()) / seconds, 2) if seconds and not in_place else None,
            "source_slide_cm_per_s": round(100.0 * float(src_step[contact].sum()) / seconds, 2) if seconds else None,
            "sink_cm": round(100.0 * (rest_h - float(tgt_ankle[:, 2].min() - floor_z)), 2),
        }

    return {
        "frames": n_frames,
        "fps": round(motion.fps, 3),
        "duration_s": round(n_frames / motion.fps, 3),
        "action": action.name,
        "in_place": in_place,
        "scale": round(float(scale), 5),
        "facing_yaw_deg": round(float(np.degrees(facing_angle)), 2),
        "bones_animated": len(basis),
        "bones_total": len(bones),
        "bones_adjusted": adjusted,
        "rest_alignment_deg": {b: round(a, 2) for b, a in aligned.items()},
        "check": {"rotation_error_deg": round(rot_err, 4), "position_error_cm": round(100.0 * pos_err, 4)},
        "travel_m": round(float(np.linalg.norm(hips_world[-1, :2] - hips_world[0, :2])), 3),
        "feet": feet,
        "warnings": warnings,
    }
