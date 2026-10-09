"""Rig automatico no padrao do Mixamo.

Como no Mixamo, tudo parte de 8 marcadores postos na vista de frente: queixo, virilha,
pulsos, cotovelos e joelhos. Deles sai um esqueleto com os mesmos nomes e a mesma
hierarquia do Mixamo (``mixamorig:Hips`` ...), e os pesos sao calculados pelo Blender.

Convencao: o personagem esta em pe, de frente para -Y, com a esquerda dele em +X e Z para
cima (como o Blender importa um modelo "de frente"). Os bracos precisam estar afastados do
corpo (T-pose ou A-pose), como o Mixamo tambem exige.

As proporcoes abaixo foram calibradas com um personagem rigado pelo proprio Mixamo.
"""

from __future__ import annotations

import bpy
import numpy as np

PREFIX = "mixamorig:"
MARKERS = ("chin", "groin", "l_wrist", "r_wrist", "l_elbow", "r_elbow", "l_knee", "r_knee")
FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")

# Fracoes do caminho quadril -> cabeca em que ficam as juntas do tronco.
SPINE_FRACTIONS = {"Spine": 0.161, "Spine1": 0.368, "Spine2": 0.551, "Neck": 0.804}
HIPS_ABOVE_GROIN = 0.045  # x altura
HIPS_OVER_CHIN = 0.61  # altura do quadril sobre a altura do queixo
UPPER_ARM_OVER_FOREARM = 1.18
# Chute dos marcadores do braco, em fracoes da reta ombro -> ponta da mao.
WRIST_FRACTION = 0.73  # quando a malha nao mostra onde o braco estreita
ELBOW_OVER_WRIST = 0.55  # o cotovelo, em fracao do caminho ate o pulso
# Dedos, em fracoes do comprimento da mao (pulso -> ponta): (ao longo da mao, para a frente).
FINGER_LAYOUT = {
    "Thumb": [(0.21, 0.115), (0.37, 0.22), (0.52, 0.295), (0.635, 0.35)],
    "Index": [(0.62, 0.24), (0.745, 0.25), (0.865, 0.255), (0.975, 0.26)],
    "Middle": [(0.63, 0.124), (0.76, 0.13), (0.88, 0.132), (1.0, 0.135)],
    "Ring": [(0.625, 0.02), (0.74, 0.022), (0.85, 0.022), (0.95, 0.022)],
    "Pinky": [(0.60, -0.095), (0.70, -0.10), (0.795, -0.105), (0.885, -0.11)],
}


class Body:
    """Os vertices do personagem em coordenadas de mundo, e medidas tiradas deles."""

    def __init__(self, meshes: list) -> None:
        chunks = []
        for obj in meshes:
            co = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
            obj.data.vertices.foreach_get("co", co)
            world = np.array(obj.matrix_world)
            chunks.append(co.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3])
        self.v = np.concatenate(chunks)
        self.lo, self.hi = self.v.min(axis=0), self.v.max(axis=0)
        self.height = float(self.hi[2] - self.lo[2])
        self.floor = float(self.lo[2])
        # Centro do corpo. A mediana dos vertices e puxada por equipamento de um lado so (coldre,
        # bolsa na cintura): a cabeca e os pes dao outras duas medidas, e fica a do meio.
        head = self.v[self.v[:, 2] > self.hi[2] - 0.08 * self.height][:, 0]
        feet = self.v[self.v[:, 2] < self.lo[2] + 0.04 * self.height][:, 0]
        self.x0 = float(np.median([np.median(self.v[:, 0]), (head.min() + head.max()) / 2, (feet.min() + feet.max()) / 2]))
        self.y0 = float((self.lo[1] + self.hi[1]) / 2)

    def slab(self, z: float, half: float | None = None) -> np.ndarray:
        half = half or 0.01 * self.height
        return self.v[np.abs(self.v[:, 2] - z) < half]

    def depth_at(self, x: float, z: float, radius: float | None = None) -> float:
        """Meio da malha na profundidade (eixo Y), na coluna em torno de (x, z)."""
        r = radius or 0.035 * self.height
        pts = self.v[(np.abs(self.v[:, 0] - x) < r) & (np.abs(self.v[:, 2] - z) < r)]
        return float((pts[:, 1].min() + pts[:, 1].max()) / 2) if len(pts) else self.y0


def estimate_markers(body: Body) -> dict[str, list[float]]:
    """Chute inicial dos marcadores, como [x, altura] em metros. O humano confere e ajusta."""
    h, x0, floor = body.height, body.x0, body.floor
    levels = np.arange(floor + 0.02 * h, floor + 0.98 * h, 0.005 * h)

    # Virilha: subindo do chao, a primeira altura em que ha malha no meio (as pernas se juntam).
    groin_z = floor + 0.48 * h
    run = 0
    for z in levels[(levels > floor + 0.25 * h) & (levels < floor + 0.65 * h)]:
        pts = body.slab(z)
        run = run + 1 if np.any(np.abs(pts[:, 0] - x0) < 0.012 * h) else 0
        if run == 3:
            groin_z = float(z - 0.01 * h)
            break

    # Queixo: um pouco acima do ponto mais estreito do pescoco.
    neck_z, narrowest = floor + 0.85 * h, np.inf
    for z in levels[(levels > floor + 0.75 * h) & (levels < floor + 0.93 * h)]:
        pts = body.slab(z)
        pts = pts[np.abs(pts[:, 0] - x0) < 0.22 * h]
        if len(pts) < 3:
            continue
        width = float(pts[:, 0].max() - pts[:, 0].min())
        if width < narrowest:
            neck_z, narrowest = float(z), width
    chin_z = neck_z + 0.25 * (body.hi[2] - neck_z)

    # A roupa engana a deteccao da virilha (calca larga, casaco). A proporcao do corpo e
    # mais confiavel: o quadril fica a ~61% da altura do queixo, o que tambem acompanha
    # personagem de cabeca grande. A deteccao so desloca esse chute um pouco.
    prior = floor + HIPS_OVER_CHIN * (chin_z - floor) - HIPS_ABOVE_GROIN * h
    groin_z = float(np.clip(groin_z, prior - 0.015 * h, prior + 0.03 * h))

    markers = {"chin": [x0, chin_z], "groin": [x0, groin_z]}
    hips_z = groin_z + HIPS_ABOVE_GROIN * h
    knee_z = floor + 0.56 * (hips_z - floor)
    for side, sign in (("l", 1.0), ("r", -1.0)):
        # Joelho: meio da perna naquela altura.
        pts = body.slab(knee_z)
        leg = pts[(sign * (pts[:, 0] - x0) > 0) & (np.abs(pts[:, 0] - x0) < 0.3 * h)]
        knee_x = float((leg[:, 0].min() + leg[:, 0].max()) / 2) if len(leg) else x0 + sign * 0.08 * h
        markers[f"{side}_knee"] = [knee_x, knee_z]

        # Braco: do ombro (chute) ate a ponta da mao, que e o ponto mais distante do ombro
        # entre os que estao afastados do corpo (para fora da linha das pernas).
        shoulder = np.array([x0 + sign * 0.105 * h, neck_z - 0.045 * h])
        # So o que esta acima do joelho: uma bota larga tambem fica "afastada do corpo" e, por
        # estar longe do ombro, ja foi tomada pela ponta da mao.
        away = body.v[(sign * (body.v[:, 0] - x0) > 0.17 * h) & (body.v[:, 2] > floor + 0.33 * h)][:, [0, 2]]
        if len(away):
            tip = away[np.argmax(np.linalg.norm(away - shoulder, axis=1))]
        else:  # bracos colados no corpo: chute de A-pose
            tip = shoulder + np.array([sign * 0.2 * h, -0.36 * h])
        wrist_at = _wrist_fraction(body, shoulder, tip, sign)
        for name, fraction in (("elbow", ELBOW_OVER_WRIST * wrist_at), ("wrist", wrist_at)):
            markers[f"{side}_{name}"] = _snap_to_limb(body, shoulder + fraction * (tip - shoulder), tip - shoulder, sign).tolist()
    return {k: [round(float(v[0]), 5), round(float(v[1]), 5)] for k, v in markers.items()}


def _wrist_fraction(body: Body, shoulder: np.ndarray, tip: np.ndarray, sign: float) -> float:
    """Em que fracao da reta ombro -> ponta da mao fica o pulso: a secao mais estreita do braco.

    A secao e medida nos dois sentidos (largura na vista de frente e profundidade) e vale a maior
    das duas: a mao de lado e fina na largura, e so a largura a tomaria pelo pulso. Sem um
    estreitamento claro, fica a proporcao de sempre.
    """
    h = body.height
    reach = float(np.linalg.norm(tip - shoulder))
    if reach < 1e-6:
        return WRIST_FRACTION
    axis = (tip - shoulder) / reach
    normal = np.array([-axis[1], axis[0]])
    flat = body.v[:, [0, 2]] - shoulder
    along, across = flat @ axis, flat @ normal
    limb = (np.abs(across) < 0.07 * h) & (sign * (body.v[:, 0] - body.x0) > 0.06 * h)
    fractions = np.arange(0.62, 0.861, 0.01)
    sizes = np.full(len(fractions), np.inf)
    for i, fraction in enumerate(fractions):
        cut = limb & (np.abs(along - fraction * reach) < 0.006 * h)
        if cut.sum() < 8:
            continue
        sizes[i] = max(float(np.ptp(across[cut])), float(np.ptp(body.v[cut, 1])))
    found = np.isfinite(sizes)
    if found.sum() < len(fractions) // 2 or sizes[found].min() > 0.9 * np.median(sizes[found]):
        return WRIST_FRACTION
    return float(fractions[np.argmin(sizes)])


def _snap_to_limb(body: Body, point: np.ndarray, axis: np.ndarray, sign: float) -> np.ndarray:
    """Leva um ponto (x, z) para o meio do braco, na direcao perpendicular ao eixo dele."""
    axis = axis / (np.linalg.norm(axis) or 1.0)
    normal = np.array([-axis[1], axis[0]])
    flat = body.v[:, [0, 2]] - point
    near = (np.abs(flat @ axis) < 0.012 * body.height) & (np.abs(flat @ normal) < 0.07 * body.height) & (sign * (body.v[:, 0] - body.x0) > 0.06 * body.height)
    if near.sum() < 3:
        return point
    across = flat[near] @ normal
    return point + normal * (across.min() + across.max()) / 2


def build_joints(body: Body, markers: dict[str, list[float]], fingers: bool = True) -> dict[str, np.ndarray]:
    """Posicao de mundo de cada junta do esqueleto do Mixamo, a partir dos marcadores."""
    h, floor = body.height, body.floor
    chin, groin = np.array(markers["chin"]), np.array(markers["groin"])
    j: dict[str, np.ndarray] = {}

    def put(name: str, x: float, y: float, z: float) -> None:
        j[name] = np.array([x, y, z], dtype=np.float64)

    # --- Pernas -------------------------------------------------------------------
    hips_z = groin[1] + HIPS_ABOVE_GROIN * h
    leg_depths = []
    for side, sign, key in (("Left", 1.0, "l"), ("Right", -1.0, "r")):
        knee = np.array(markers[f"{key}_knee"])
        up_x = groin[0] + (knee[0] - groin[0]) * 0.72
        up_z = hips_z + 0.004 * h
        ankle_z = floor + 0.24 * (knee[1] - floor)
        # O tornozelo continua a reta coxa -> joelho.
        ankle_x = knee[0] + (knee[0] - up_x) * (knee[1] - ankle_z) / max(up_z - knee[1], 1e-6)
        up_depth = body.depth_at(up_x, up_z - 0.06 * h)
        knee_depth = body.depth_at(knee[0], knee[1])
        # No tornozelo a coluna de vertices pega o pe inteiro; a perna logo acima e melhor guia.
        ankle_depth = body.depth_at(ankle_x, ankle_z + 0.05 * h)
        foot = body.v[(sign * (body.v[:, 0] - groin[0]) > 0) & (body.v[:, 2] < ankle_z) & (np.abs(body.v[:, 0] - ankle_x) < 0.08 * h)]
        toe_tip = float(foot[:, 1].min()) if len(foot) else ankle_depth - 0.1 * h  # frente = -Y
        leg_depths.append(up_depth)
        put(f"{side}UpLeg", up_x, up_depth, up_z)
        put(f"{side}Leg", knee[0], knee_depth, knee[1])
        put(f"{side}Foot", ankle_x, ankle_depth, ankle_z)
        toe_z = floor + 0.35 * (ankle_z - floor)
        put(f"{side}ToeBase", ankle_x + sign * 0.012 * h, ankle_depth + 0.6 * (toe_tip - ankle_depth), toe_z)
        put(f"{side}Toe_End", ankle_x + sign * 0.02 * h, toe_tip, toe_z)

    # --- Tronco e cabeca ------------------------------------------------------------
    hips_depth = float(np.mean(leg_depths))
    head_depth = body.depth_at(chin[0], chin[1] + 0.03 * h, 0.05 * h)
    put("Hips", groin[0], hips_depth, hips_z)
    put("Head", chin[0], head_depth, chin[1])
    for name, fraction in SPINE_FRACTIONS.items():
        j[name] = j["Hips"] + fraction * (j["Head"] - j["Hips"])
    put("HeadTop_End", chin[0], head_depth, float(body.hi[2]))

    # --- Bracos -----------------------------------------------------------------------
    for side, sign, key in (("Left", 1.0, "l"), ("Right", -1.0, "r")):
        elbow2, wrist2 = np.array(markers[f"{key}_elbow"]), np.array(markers[f"{key}_wrist"])
        elbow = np.array([elbow2[0], body.depth_at(*elbow2), elbow2[1]])
        wrist = np.array([wrist2[0], body.depth_at(*wrist2), wrist2[1]])
        # O ombro fica a um braco de distancia do cotovelo, na direcao do proprio braco, medida
        # na malha. So com o braco reto ela e a continuacao do antebraco: com o cotovelo um
        # pouco dobrado (o normal numa A-pose relaxada), essa reta levava o ombro para o pescoco.
        upper = _upper_arm_axis(body, sign, elbow2, wrist2, float(elbow[1])) * np.linalg.norm(wrist2 - elbow2) * UPPER_ARM_OVER_FOREARM
        shoulder = np.array([elbow2[0] + upper[0], 0.0, elbow2[1] + upper[1]])
        shoulder[1] = 0.5 * (elbow[1] + j["Spine2"][1])
        # Nunca para dentro do tronco: no minimo a meia largura do pescoco.
        shoulder[0] = chin[0] + sign * max(sign * (shoulder[0] - chin[0]), 0.06 * h)
        j[f"{side}Arm"] = shoulder
        clavicle = j["Neck"].copy()
        clavicle[0] = chin[0] + 0.28 * (shoulder[0] - chin[0])
        clavicle[2] = min(j["Neck"][2] - 0.008 * h, shoulder[2] + 0.02 * h)
        j[f"{side}Shoulder"] = clavicle
        j[f"{side}ForeArm"] = elbow
        j[f"{side}Hand"] = wrist
        if fingers:
            j.update(_finger_joints(body, side, elbow, wrist))
    return j


def _upper_arm_axis(body: Body, sign: float, elbow2: np.ndarray, wrist2: np.ndarray, elbow_y: float) -> np.ndarray:
    """Direcao (x, altura) do cotovelo para o ombro, medida na malha.

    Parte da continuacao do antebraco e a corrige pelo meio do braco em secoes acima do
    cotovelo. Onde o braco esta solto do tronco, o meio e o da secao; onde ja encostou nele
    (perto da axila numa A-pose), so o contorno de fora vale, e o meio fica a um raio dele.
    Sem secoes bastantes, ou sem conseguir separar o braco do tronco ja no cotovelo, devolve a
    continuacao do antebraco, que era a regra de antes.
    """
    h = body.height
    straight = (elbow2 - wrist2) / np.linalg.norm(elbow2 - wrist2)
    outward = np.array([sign * straight[1], -sign * straight[0]])  # para longe do corpo (em T-pose, para cima)
    flat = body.v[:, [0, 2]] - elbow2
    along, across = flat @ straight, flat @ outward
    near = (np.abs(body.v[:, 1] - elbow_y) < 0.12 * h) & (np.abs(across) < 0.16 * h)

    def section(s: float) -> tuple[float, float] | None:
        """O trecho de malha mais de fora na secao a ``s`` do cotovelo: (lado de dentro, lado de fora)."""
        values = np.sort(across[near & (np.abs(along - s) < 0.006 * h)])
        if len(values) < 6:
            return None
        gaps = np.nonzero(np.diff(values) > 0.012 * h)[0]
        return float(values[gaps[-1] + 1 if len(gaps) else 0]), float(values[-1])

    at_elbow = section(0.0)
    if at_elbow is None or at_elbow[1] - at_elbow[0] > 0.12 * h:
        return straight
    width = at_elbow[1] - at_elbow[0]
    radius = 0.5 * width
    length = float(np.linalg.norm(wrist2 - elbow2)) * UPPER_ARM_OVER_FOREARM
    samples = [(0.0, 0.0)]  # o cotovelo e o marcador que o humano conferiu
    for s in np.linspace(0.15, 0.70, 12) * length:
        cut = section(float(s))
        if cut is None:
            continue
        if cut[1] - cut[0] < 1.8 * width:
            radius = 0.5 * (cut[1] - cut[0])
            samples.append((float(s), 0.5 * (cut[0] + cut[1])))
        else:
            samples.append((float(s), cut[1] - radius))
    if len(samples) < 6:
        return straight
    s, middle = np.array(samples).T
    angle = float(np.clip(np.arctan((s @ middle) / (s @ s)), -np.radians(30.0), np.radians(30.0)))
    return straight * np.cos(angle) + outward * np.sin(angle)


def _hand_frame(body: Body, sign: float, elbow: np.ndarray, wrist: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    """Eixo da mao, lado do polegar, comprimento e deslocamento do gabarito dos dedos.

    A mao raramente continua a reta do antebraco (pulso dobrado, mao relaxada): o eixo e o
    plano dela sao medidos nos vertices alem do pulso, para os ossos dos dedos cairem dentro
    dos dedos. Sem malha bastante, ou se o que foi medido nao parece uma mao, vale a reta do
    antebraco com o polegar para a frente (-Y), que era a regra de antes.
    """
    h = body.height
    forearm = (wrist - elbow) / np.linalg.norm(wrist - elbow)
    rel = body.v - wrist
    t = rel @ forearm
    off_axis = np.linalg.norm(rel - np.outer(t, forearm), axis=1)
    # Comprimento da mao: ate onde a malha vai alem do pulso, perto do eixo do braco.
    reach = t[(t > 0) & (off_axis < 0.09 * h)]
    length = float(np.clip(reach.max() if len(reach) else 0.11 * h, 0.06 * h, 0.16 * h))
    front = np.array([0.0, -1.0, 0.0])
    forward = front - (front @ forearm) * forearm
    forward /= np.linalg.norm(forward) or 1.0
    straight = (forearm, forward, length, np.zeros(3))

    points = rel[(t > 0) & (t < 0.16 * h) & (off_axis < 0.065 * h)]
    if len(points) < 50:
        return straight
    spread, axes = np.linalg.eigh(np.cov((points - points.mean(axis=0)).T))
    order = np.argsort(spread)[::-1]
    along = axes[:, order[0]] * (1.0 if axes[:, order[0]] @ forearm >= 0 else -1.0)
    if along @ forearm < np.cos(np.radians(50.0)) or spread[order[0]] < 1.5 * spread[order[1]]:
        return straight
    across = axes[:, order[1]]
    lean = across @ (front - (front @ along) * along)
    if abs(lean) >= 0.35:
        across = across * np.sign(lean)
    else:  # palma virada para a frente ou para tras: o polegar fica para fora do corpo
        across = across * (np.sign(sign * across[0]) or 1.0)
    length = float(np.clip((points @ along).max(), 0.06 * h, 0.16 * h))
    # O gabarito tem o meio da mao (entre o indicador e o minimo) a esta distancia do eixo.
    template_middle = 0.5 * (FINGER_LAYOUT["Index"][0][1] + FINGER_LAYOUT["Pinky"][0][1]) * length
    palm = np.cross(along, across)
    shift = across * float(np.clip(np.median(points @ across) - template_middle, -0.03 * h, 0.03 * h))
    shift = shift + palm * float(np.clip(np.median(points @ palm), -0.03 * h, 0.03 * h))
    return along, across, length, shift


def _finger_joints(body: Body, side: str, elbow: np.ndarray, wrist: np.ndarray) -> dict[str, np.ndarray]:
    along, forward, length, shift = _hand_frame(body, 1.0 if side == "Left" else -1.0, elbow, wrist)
    out = {}
    for finger, layout in FINGER_LAYOUT.items():
        for i, (a, f) in enumerate(layout, start=1):
            out[f"{side}Hand{finger}{i}"] = wrist + shift + along * (a * length) + forward * (f * length)
    return out


def _hierarchy(fingers: bool) -> list[tuple[str, str | None]]:
    bones: list[tuple[str, str | None]] = [("Hips", None), ("Spine", "Hips"), ("Spine1", "Spine"), ("Spine2", "Spine1"), ("Neck", "Spine2"), ("Head", "Neck"), ("HeadTop_End", "Head")]
    for side in ("Left", "Right"):
        bones += [(f"{side}Shoulder", "Spine2"), (f"{side}Arm", f"{side}Shoulder"), (f"{side}ForeArm", f"{side}Arm"), (f"{side}Hand", f"{side}ForeArm")]
        if fingers:
            for finger in FINGERS:
                parent = f"{side}Hand"
                for i in range(1, 5):
                    bones.append((f"{side}Hand{finger}{i}", parent))
                    parent = f"{side}Hand{finger}{i}"
        bones += [(f"{side}UpLeg", "Hips"), (f"{side}Leg", f"{side}UpLeg"), (f"{side}Foot", f"{side}Leg"), (f"{side}ToeBase", f"{side}Foot"), (f"{side}Toe_End", f"{side}ToeBase")]
    return bones


def build_armature(joints: dict[str, np.ndarray], fingers: bool = True):
    """Cria a armature do Blender com os nomes e a hierarquia do Mixamo."""
    bones = [(n, p) for n, p in _hierarchy(fingers) if n in joints]
    children: dict[str, list[str]] = {}
    for name, parent in bones:
        if parent:
            children.setdefault(parent, []).append(name)

    data = bpy.data.armatures.new("Armature")
    arm = bpy.data.objects.new("Armature", data)
    bpy.context.scene.collection.objects.link(arm)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for name, parent in bones:
        eb = data.edit_bones.new(PREFIX + name)
        head = joints[name]
        if name == "Hips":
            tail = joints["Spine"]
        elif name in children:
            tail = joints[children[name][0]]
        else:  # folha: continua na direcao do pai
            back = head - joints[parent]
            tail = head + back / (np.linalg.norm(back) or 1.0) * max(np.linalg.norm(back) * 0.5, 1e-3)
        eb.head, eb.tail = head.tolist(), tail.tolist()
        if parent:
            eb.parent = data.edit_bones[PREFIX + parent]
        eb.use_deform = not (name.endswith("_End") or name[-1] == "4")
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def skin(arm, meshes: list, height: float) -> dict:
    """Calcula os pesos e liga as malhas a armature. Devolve o metodo usado e avisos.

    Os pesos automaticos do Blender (bone heat) falham em malha aberta ou com faces
    internas, comuns em modelo gerado por IA. Por isso eles sao calculados numa copia
    refeita por voxels, que e fechada, e transferidos para a malha de verdade.
    """
    notes: list[str] = []

    def select(objects: list, active) -> None:
        for obj in bpy.context.view_layer.objects:
            obj.select_set(False)
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = active

    # Copia unica de todas as malhas, refeita por voxels.
    copies = []
    for obj in meshes:
        copy = obj.copy()
        copy.data = obj.data.copy()
        bpy.context.scene.collection.objects.link(copy)
        copies.append(copy)
    select(copies, copies[0])
    if len(copies) > 1:
        bpy.ops.object.join()
    proxy = bpy.context.view_layer.objects.active
    proxy.name = "ProxyPesos"
    for group in list(proxy.vertex_groups):
        proxy.vertex_groups.remove(group)
    for modifier in list(proxy.modifiers):
        proxy.modifiers.remove(modifier)
    proxy.data.remesh_voxel_size = height / 160.0
    proxy.data.remesh_voxel_adaptivity = 0.0
    select([proxy], proxy)
    bpy.ops.object.voxel_remesh()

    select([proxy, arm], arm)
    method = "bone heat"
    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    except RuntimeError as exc:
        notes.append(f"Pesos automáticos falharam ({exc}); usando pesos por distância.")
    if not any(len(v.groups) for v in proxy.data.vertices):
        # Sem solucao do bone heat: pesos por envelope (distancia aos ossos).
        method = "envelope"
        select([proxy, arm], arm)
        bpy.ops.object.parent_set(type="ARMATURE_ENVELOPE")
        if "bone heat" not in " ".join(notes):
            notes.append("Os pesos automáticos não acharam solução; usados pesos por distância aos ossos, que são mais grosseiros.")

    for obj in meshes:
        for group in list(obj.vertex_groups):
            obj.vertex_groups.remove(group)
        for modifier in [m for m in obj.modifiers if m.type == "ARMATURE"]:
            obj.modifiers.remove(modifier)
        transfer = obj.modifiers.new("PesosDoProxy", "DATA_TRANSFER")
        transfer.object = proxy
        transfer.use_vert_data = True
        transfer.data_types_verts = {"VGROUP_WEIGHTS"}
        transfer.vert_mapping = "POLYINTERP_NEAREST"
        select([obj], obj)
        bpy.ops.object.datalayout_transfer(modifier=transfer.name)
        bpy.ops.object.modifier_apply(modifier=transfer.name)
        # Limite de 4 influencias por vertice, como as engines esperam.
        bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
        bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
        world = obj.matrix_world.copy()
        obj.parent = arm
        obj.matrix_world = world
        obj.modifiers.new("Armature", "ARMATURE").object = arm

    bpy.data.objects.remove(proxy, do_unlink=True)
    deform = {b.name for b in arm.data.bones if b.use_deform}
    unweighted = 0
    for obj in meshes:
        groups = {g.index for g in obj.vertex_groups if g.name in deform}
        unweighted += sum(1 for v in obj.data.vertices if not any(g.group in groups and g.weight > 1e-5 for g in v.groups))
    if unweighted:
        notes.append(f"{unweighted} vértice(s) ficaram sem peso.")
    return {"method": method, "unweighted_vertices": unweighted, "notes": notes}
