"""Confere o mapeamento de ossos em várias convenções de nomes. Roda sem Blender:

    uv run python tests/check_rigmap.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender"))

from ponte_bl import rigmap  # noqa: E402

# Cada rig: lista de (osso, pai) com a espinha dorsal de um humanoide.
RIGS = {
    "mixamo": {
        "prefix": "mixamorig:",
        "hips": "Hips", "torso": ["Spine", "Spine1", "Spine2"], "neck": ["Neck"], "head": "Head",
        "shoulder": "{S}Shoulder", "arm": "{S}Arm", "forearm": "{S}ForeArm", "hand": "{S}Hand",
        "upleg": "{S}UpLeg", "leg": "{S}Leg", "foot": "{S}Foot", "toe": "{S}ToeBase",
        "sides": ("Left", "Right"), "finger": "{S}HandIndex{n}", "type": "mixamo",
    },
    "unreal": {
        "prefix": "",
        "hips": "pelvis", "torso": ["spine_01", "spine_02", "spine_03"], "neck": ["neck_01"], "head": "head",
        "shoulder": "clavicle_{S}", "arm": "upperarm_{S}", "forearm": "lowerarm_{S}", "hand": "hand_{S}",
        "upleg": "thigh_{S}", "leg": "calf_{S}", "foot": "foot_{S}", "toe": "ball_{S}",
        "sides": ("l", "r"), "finger": "index_0{n}_{S}", "type": "unreal",
    },
    "unity": {
        "prefix": "",
        "hips": "Hips", "torso": ["Spine", "Chest", "UpperChest"], "neck": ["Neck"], "head": "Head",
        "shoulder": "{S}Shoulder", "arm": "{S}UpperArm", "forearm": "{S}LowerArm", "hand": "{S}Hand",
        "upleg": "{S}UpperLeg", "leg": "{S}LowerLeg", "foot": "{S}Foot", "toe": "{S}Toes",
        "sides": ("Left", "Right"), "finger": "{S}IndexProximal", "type": "humanoide",
    },
    "blender": {
        "prefix": "",
        "hips": "hips", "torso": ["spine", "chest"], "neck": ["neck"], "head": "head",
        "shoulder": "shoulder.{S}", "arm": "upper_arm.{S}", "forearm": "forearm.{S}", "hand": "hand.{S}",
        "upleg": "thigh.{S}", "leg": "shin.{S}", "foot": "foot.{S}", "toe": "toe.{S}",
        "sides": ("L", "R"), "finger": "f_index.0{n}.{S}", "type": "humanoide",
    },
    "vrm": {
        "prefix": "J_Bip_",
        "hips": "C_Hips", "torso": ["C_Spine", "C_Chest", "C_UpperChest"], "neck": ["C_Neck"], "head": "C_Head",
        "shoulder": "{S}_Shoulder", "arm": "{S}_UpperArm", "forearm": "{S}_LowerArm", "hand": "{S}_Hand",
        "upleg": "{S}_UpperLeg", "leg": "{S}_LowerLeg", "foot": "{S}_Foot", "toe": "{S}_ToeBase",
        "sides": ("L", "R"), "finger": "{S}_Index{n}", "type": "humanoide",
    },
    "biped": {
        "prefix": "Bip001 ",
        "hips": "Pelvis", "torso": ["Spine", "Spine1"], "neck": ["Neck"], "head": "Head",
        "shoulder": "{S} Clavicle", "arm": "{S} UpperArm", "forearm": "{S} Forearm", "hand": "{S} Hand",
        "upleg": "{S} Thigh", "leg": "{S} Calf", "foot": "{S} Foot", "toe": "{S} Toe0",
        "sides": ("L", "R"), "finger": None, "type": "humanoide",
    },
    # Esqueleto de captura (XSens, 100STYLE): o osso leva o nome da junta em que começa.
    "captura": {
        "prefix": "",
        "hips": "Hips", "torso": ["Chest", "Chest2", "Chest3", "Chest4"], "neck": ["Neck"], "head": "Head",
        "shoulder": "{S}Collar", "arm": "{S}Shoulder", "forearm": "{S}Elbow", "hand": "{S}Wrist",
        "upleg": "{S}Hip", "leg": "{S}Knee", "foot": "{S}Ankle", "toe": "{S}Toe",
        "sides": ("Left", "Right"), "finger": None, "type": "humanoide",
    },
}  # fmt: skip


def build(spec: dict) -> list[tuple[str, str | None]]:
    p = spec["prefix"]
    bones: list[tuple[str, str | None]] = [(p + spec["hips"], None)]
    parent = p + spec["hips"]
    for name in spec["torso"] + spec["neck"] + [spec["head"]]:
        bones.append((p + name, parent))
        parent = p + name
    chest = p + spec["torso"][-1]
    for side in spec["sides"]:
        parent = chest
        for part in ("shoulder", "arm", "forearm", "hand"):
            bones.append((p + spec[part].format(S=side), parent))
            parent = p + spec[part].format(S=side)
        if spec["finger"]:
            bones.append((p + spec["finger"].format(S=side, n=1), parent))
        parent = p + spec["hips"]
        for part in ("upleg", "leg", "foot", "toe"):
            bones.append((p + spec[part].format(S=side), parent))
            parent = p + spec[part].format(S=side)
    # Ossos que nao devem ser confundidos com nada.
    bones += [(p + "Prop_Weapon", p + spec["hips"]), (p + "Tail_01", p + spec["hips"])]
    return bones


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    failures = 0
    for name, spec in RIGS.items():
        bones = build(spec)
        mapping = rigmap.build_mapping(bones)
        rig_type = rigmap.detect_rig_type([b for b, _ in bones])["type"]
        problems = []
        if not mapping["retargetable"]:
            problems.append(f"faltam {mapping['missing_required']}")
        if mapping["torso"] != [spec["prefix"] + b for b in spec["torso"]]:
            problems.append(f"torso {mapping['torso']}")
        if mapping["neck"] != [spec["prefix"] + b for b in spec["neck"]]:
            problems.append(f"pescoço {mapping['neck']}")
        if rig_type != spec["type"]:
            problems.append(f"tipo {rig_type} (esperado {spec['type']})")
        for part in ("shoulder", "arm", "forearm", "hand", "upleg", "leg", "foot", "toe"):
            for side, token in zip("lr", spec["sides"]):
                bone = spec["prefix"] + spec[part].format(S=token)
                if mapping["slots"].get(f"{side}_{part}") != bone:
                    problems.append(f"{side}_{part} é {mapping['slots'].get(f'{side}_{part}')} (esperado {bone})")
        if spec["finger"] and "l_index1" not in mapping["slots"]:
            problems.append("sem dedo indicador")
        if any("Prop" in b or "Tail" in b for b in mapping["slots"].values()):
            problems.append("mapeou osso que não é do corpo")
        plan = rigmap.build_plan(mapping) if mapping["retargetable"] else []
        sources = {item["bone"]: item["joint"] for item in plan}
        if plan and sources.get(mapping["slots"]["l_upleg"]) != "LeftLeg":
            problems.append("coxa esquerda não recebe LeftLeg do SOMA")
        if plan and sources.get(mapping["torso"][-1]) != "Chest":
            problems.append("último osso da coluna não recebe Chest")
        status = "ok  " if not problems else "FALHA"
        failures += bool(problems)
        print(f"{status} {name:8s} {len(plan):2d} ossos no plano" + (f"  -> {'; '.join(problems)}" if problems else ""))

    # Esqueleto que é a fonte da animação: cada osso responde por uma junta do SOMA, sem nome repetido.
    bones = build(RIGS["captura"])
    _, soma = rigmap.source_joint_names(bones)
    names = rigmap.rename_to_soma([b for b, _ in bones], soma)
    renamed = dict(zip((b for b, _ in bones), names))
    expected = {"Hips": "Hips", "Chest": "Spine1", "Chest2": "Spine2", "Chest3": "Chest3", "Chest4": "Chest", "Neck": "Neck1", "LeftCollar": "LeftShoulder", "LeftShoulder": "LeftArm", "LeftElbow": "LeftForeArm", "LeftWrist": "LeftHand", "RightHip": "RightLeg", "RightKnee": "RightShin", "RightAnkle": "RightFoot", "RightToe": "RightToeBase"}  # fmt: skip
    problems = [f"{bone} virou {renamed[bone]} (esperado {joint})" for bone, joint in expected.items() if renamed[bone] != joint]
    if len(set(names)) != len(names):
        problems.append("nome repetido depois da troca")
    # Um osso sem papel que já usava um nome do SOMA cede o nome a quem responde por ele.
    if rigmap.rename_to_soma(["Chest", "Spine"], {"Spine": "Chest"}) != ["Chest_fonte", "Chest"]:
        problems.append("osso sem papel ficou com o nome de uma junta do SOMA")
    failures += bool(problems)
    print(f"{'FALHA' if problems else 'ok  '} nomes do SOMA numa fonte de captura" + (f"  -> {'; '.join(problems)}" if problems else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
