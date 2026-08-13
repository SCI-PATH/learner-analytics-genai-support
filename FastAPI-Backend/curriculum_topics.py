"""
Auto-generated curriculum catalog (do not hand-edit).

Regenerate with:
    python Scripts/build_full_curriculum.py

Format: G{grade}_C{chapter}_{DOMAIN}_{CONCEPT}
Skills: 128 across grades 6–9 (full chapter coverage).
"""

from __future__ import annotations

from typing import Any

# Canonical ordered topic IDs
TOPIC_IDS: list[str] = [
    "G6_C1_ORG_CHARS",
    "G6_C1_ORG_DIFF",
    "G6_C2_MAT_STATES",
    "G6_C2_MAT_PROPS",
    "G6_C3_WAT_STATES",
    "G6_C3_WAT_IMPORT",
    "G6_C4_ENE_SOURCES",
    "G6_C4_ENE_FORMS",
    "G6_C5_LIG_SEE",
    "G6_C5_LIG_RAYS",
    "G6_C6_SOU_PRODUCE",
    "G6_C6_SOU_DIVERSE",
    "G6_C7_MAG_POLES",
    "G6_C7_MAG_FORCES",
    "G6_C8_ELE_CIRCUITS",
    "G6_C8_ELE_CONDINS",
    "G6_C9_HEA_GEN",
    "G6_C9_HEA_ENV",
    "G6_C10_FOO_INTER",
    "G6_C10_FOO_NUTR",
    "G6_C11_WEA_WEATHER",
    "G6_C11_WEA_DISASTER",
    "G7_C1_PLA_DIVER",
    "G7_C1_PLA_CLASSIF",
    "G7_C2_STA_CHARGES",
    "G7_C2_STA_CAPACIT",
    "G7_C3_ELE_SOURCES",
    "G7_C3_ELE_CURRENTS",
    "G7_C4_WAT_SOLVENT",
    "G7_C4_WAT_COOLANT",
    "G7_C5_ACI_IDENTIF",
    "G7_C5_ACI_INDICAT",
    "G7_C6_ANI_CLASSIF",
    "G7_C6_ANI_ADAPTAT",
    "G7_C7_ENE_FORMS",
    "G7_C7_ENE_TRANSF",
    "G7_C8_EAR_STRUCT",
    "G7_C8_EAR_TECTON",
    "G7_C9_LIG_SHADOWS",
    "G7_C9_LIG_MIRRORS",
    "G7_C10_MIC_LIGHT",
    "G7_C10_MIC_ELECTR",
    "G7_C11_SOU_PRODUCE",
    "G7_C11_SOU_PROPAG",
    "G7_C12_BIO_LEVELS",
    "G7_C12_BIO_SYSTEMS",
    "G7_C13_ATM_LAYERS",
    "G7_C13_ATM_AIR",
    "G7_C14_HEA_MEASURE",
    "G7_C14_HEA_TRANSF",
    "G7_C15_SOI_TYPES",
    "G7_C15_SOI_EROSION",
    "G7_C16_FOR_DIST",
    "G7_C16_FOR_FORCE",
    "G7_C17_NUT_FOOD",
    "G7_C17_NUT_TESTS",
    "G7_C18_ROC_KINDS",
    "G7_C18_ROC_CYCLE",
    "G7_C19_ENE_RENEW",
    "G7_C19_ENE_SUSTAIN",
    "G8_C1_MIC_INTRO",
    "G8_C1_MIC_EFFECTS",
    "G8_C2_ANI_INVERT",
    "G8_C2_ANI_VERT",
    "G8_C3_PLA_LEAVES",
    "G8_C3_PLA_STEMROOT",
    "G8_C4_MAT_PARTICLE",
    "G8_C4_MAT_PROPS",
    "G8_C5_SOU_INSTR",
    "G8_C5_SOU_VIBRATE",
    "G8_C6_MAG_FIELD",
    "G8_C6_MAG_TYPES",
    "G8_C7_ELE_CURRENT",
    "G8_C7_ELE_RESIST",
    "G8_C8_CHA_PHYSCHEM",
    "G8_C8_CHA_COMBUST",
    "G8_C9_HUM_EXCRET",
    "G8_C9_HUM_NERVSKIN",
    "G8_C10_ELE_CIRCUITS",
    "G8_C10_ELE_EFFECTS",
    "G8_C11_PHO_PROCESS",
    "G8_C11_PHO_TRANSP",
    "G8_C12_LIF_ANIMAL",
    "G8_C12_LIF_PLANT",
    "G8_C13_FOO_METHODS",
    "G8_C13_FOO_LABEL",
    "G8_C14_SOL_SYSTEM",
    "G8_C14_SOL_EXPLORE",
    "G8_C15_DIS_HYDRO",
    "G8_C15_DIS_LIGHTNG",
    "G9_C1_MIC_ENV",
    "G9_C1_MIC_EFFECTS",
    "G9_C2_SEN_EYE",
    "G9_C2_SEN_EAR",
    "G9_C3_MAT_ELEMENTS",
    "G9_C3_MAT_MIXTURES",
    "G9_C4_FOR_FORCE",
    "G9_C4_FOR_GRAPH",
    "G9_C5_PRE_PRESSURE",
    "G9_C5_PRE_APPLY",
    "G9_C6_CIR_HEART",
    "G9_C6_CIR_BLOOD",
    "G9_C7_PGS_INTRO",
    "G9_C7_PGS_ARTIF",
    "G9_C8_MOV_ANIMAL",
    "G9_C8_MOV_PLANT",
    "G9_C9_EVO_ORIGIN",
    "G9_C9_EVO_BIODIV",
    "G9_C10_ELE_LYSIS",
    "G9_C10_ELE_PLATE",
    "G9_C11_DEN_INTRO",
    "G9_C11_DEN_HYDRO",
    "G9_C12_BIO_INTRO",
    "G9_C12_BIO_ECO",
    "G9_C13_GRN_CONCEPT",
    "G9_C13_GRN_AGRI",
    "G9_C14_WAV_REFLECT",
    "G9_C14_WAV_REFRACT",
    "G9_C15_MAC_LEVER",
    "G9_C15_MAC_PULLEY",
    "G9_C16_NANO_INTRO",
    "G9_C16_NANO_APPS",
    "G9_C17_LIG_OCCUR",
    "G9_C17_LIG_PREVENT",
    "G9_C18_DIS_TYPES",
    "G9_C18_DIS_WARMING",
    "G9_C19_RES_WATER",
    "G9_C19_RES_MINERAL"
]

TOPIC_META: dict[str, dict[str, Any]] = {
    "G6_C1_ORG_CHARS": {
        "grade": 6,
        "chapter": 1,
        "chapter_title": "Wonders of the Living World",
        "part": "full",
        "skill_label": "Characteristics of organisms",
        "curriculum_reference": "Ch.1: Characteristics of organisms"
    },
    "G6_C1_ORG_DIFF": {
        "grade": 6,
        "chapter": 1,
        "chapter_title": "Wonders of the Living World",
        "part": "full",
        "skill_label": "Differences between plants and animals",
        "curriculum_reference": "Ch.1: Differences between plants and animals"
    },
    "G6_C2_MAT_STATES": {
        "grade": 6,
        "chapter": 2,
        "chapter_title": "Things Around Us",
        "part": "full",
        "skill_label": "States of matter",
        "curriculum_reference": "Ch.2: States of matter"
    },
    "G6_C2_MAT_PROPS": {
        "grade": 6,
        "chapter": 2,
        "chapter_title": "Things Around Us",
        "part": "full",
        "skill_label": "Specific properties of solid matter",
        "curriculum_reference": "Ch.2: Specific properties of solid matter"
    },
    "G6_C3_WAT_STATES": {
        "grade": 6,
        "chapter": 3,
        "chapter_title": "Water as a Natural Resource",
        "part": "full",
        "skill_label": "States and types of water",
        "curriculum_reference": "Ch.3: States and types of water"
    },
    "G6_C3_WAT_IMPORT": {
        "grade": 6,
        "chapter": 3,
        "chapter_title": "Water as a Natural Resource",
        "part": "full",
        "skill_label": "Importance of water and conservation",
        "curriculum_reference": "Ch.3: Importance of water and conservation"
    },
    "G6_C4_ENE_SOURCES": {
        "grade": 6,
        "chapter": 4,
        "chapter_title": "Energy in Day to Day Life",
        "part": "full",
        "skill_label": "Energy sources and their applications",
        "curriculum_reference": "Ch.4: Energy sources and their applications"
    },
    "G6_C4_ENE_FORMS": {
        "grade": 6,
        "chapter": 4,
        "chapter_title": "Energy in Day to Day Life",
        "part": "full",
        "skill_label": "Forms of energy in daily life",
        "curriculum_reference": "Ch.4: Forms of energy in daily life"
    },
    "G6_C5_LIG_SEE": {
        "grade": 6,
        "chapter": 5,
        "chapter_title": "Light and Vision",
        "part": "full",
        "skill_label": "How we see; sources and transmission of light",
        "curriculum_reference": "Ch.5: How we see; sources and transmission of light"
    },
    "G6_C5_LIG_RAYS": {
        "grade": 6,
        "chapter": 5,
        "chapter_title": "Light and Vision",
        "part": "full",
        "skill_label": "Light rays, beams, and applications",
        "curriculum_reference": "Ch.5: Light rays, beams, and applications"
    },
    "G6_C6_SOU_PRODUCE": {
        "grade": 6,
        "chapter": 6,
        "chapter_title": "Sound and Hearing",
        "part": "full",
        "skill_label": "Producing and hearing sounds",
        "curriculum_reference": "Ch.6: Producing and hearing sounds"
    },
    "G6_C6_SOU_DIVERSE": {
        "grade": 6,
        "chapter": 6,
        "chapter_title": "Sound and Hearing",
        "part": "full",
        "skill_label": "Diversity of sounds; music and noise",
        "curriculum_reference": "Ch.6: Diversity of sounds; music and noise"
    },
    "G6_C7_MAG_POLES": {
        "grade": 6,
        "chapter": 7,
        "chapter_title": "Magnets",
        "part": "full",
        "skill_label": "Magnetic poles, types, and behaviour",
        "curriculum_reference": "Ch.7: Magnetic poles, types, and behaviour"
    },
    "G6_C7_MAG_FORCES": {
        "grade": 6,
        "chapter": 7,
        "chapter_title": "Magnets",
        "part": "full",
        "skill_label": "Magnetic interactions and forces",
        "curriculum_reference": "Ch.7: Magnetic interactions and forces"
    },
    "G6_C8_ELE_CIRCUITS": {
        "grade": 6,
        "chapter": 8,
        "chapter_title": "Electricity for a Comfortable Life",
        "part": "full",
        "skill_label": "Preparation of circuits and generating electricity",
        "curriculum_reference": "Ch.8: Preparation of circuits and generating electricity"
    },
    "G6_C8_ELE_CONDINS": {
        "grade": 6,
        "chapter": 8,
        "chapter_title": "Electricity for a Comfortable Life",
        "part": "full",
        "skill_label": "Conductors and insulators; safety",
        "curriculum_reference": "Ch.8: Conductors and insulators; safety"
    },
    "G6_C9_HEA_GEN": {
        "grade": 6,
        "chapter": 9,
        "chapter_title": "Heat and Its Effects",
        "part": "full",
        "skill_label": "Heat generation and effects",
        "curriculum_reference": "Ch.9: Heat generation and effects"
    },
    "G6_C9_HEA_ENV": {
        "grade": 6,
        "chapter": 9,
        "chapter_title": "Heat and Its Effects",
        "part": "full",
        "skill_label": "Effects of heat on the environment",
        "curriculum_reference": "Ch.9: Effects of heat on the environment"
    },
    "G6_C10_FOO_INTER": {
        "grade": 6,
        "chapter": 10,
        "chapter_title": "Food Related Interactions",
        "part": "full",
        "skill_label": "Food related interactions in ecosystems",
        "curriculum_reference": "Ch.10: Food related interactions in ecosystems"
    },
    "G6_C10_FOO_NUTR": {
        "grade": 6,
        "chapter": 10,
        "chapter_title": "Food Related Interactions",
        "part": "full",
        "skill_label": "Nutrition relationships among organisms",
        "curriculum_reference": "Ch.10: Nutrition relationships among organisms"
    },
    "G6_C11_WEA_WEATHER": {
        "grade": 6,
        "chapter": 11,
        "chapter_title": "Weather and Climate",
        "part": "full",
        "skill_label": "Weather, climate, and measurement",
        "curriculum_reference": "Ch.11: Weather, climate, and measurement"
    },
    "G6_C11_WEA_DISASTER": {
        "grade": 6,
        "chapter": 11,
        "chapter_title": "Weather and Climate",
        "part": "full",
        "skill_label": "Natural disasters from climatic changes",
        "curriculum_reference": "Ch.11: Natural disasters from climatic changes"
    },
    "G7_C1_PLA_DIVER": {
        "grade": 7,
        "chapter": 1,
        "chapter_title": "Plant Diversity",
        "part": "I",
        "skill_label": "Morphological features and plant diversity",
        "curriculum_reference": "Ch.1: Morphological features and plant diversity"
    },
    "G7_C1_PLA_CLASSIF": {
        "grade": 7,
        "chapter": 1,
        "chapter_title": "Plant Diversity",
        "part": "I",
        "skill_label": "Monocotyledonous and dicotyledonous plants",
        "curriculum_reference": "Ch.1: Monocotyledonous and dicotyledonous plants"
    },
    "G7_C2_STA_CHARGES": {
        "grade": 7,
        "chapter": 2,
        "chapter_title": "Static Electricity",
        "part": "I",
        "skill_label": "Charging objects and types of static charge",
        "curriculum_reference": "Ch.2: Charging objects and types of static charge"
    },
    "G7_C2_STA_CAPACIT": {
        "grade": 7,
        "chapter": 2,
        "chapter_title": "Static Electricity",
        "part": "I",
        "skill_label": "Capacitors and static electricity phenomena",
        "curriculum_reference": "Ch.2: Capacitors and static electricity phenomena"
    },
    "G7_C3_ELE_SOURCES": {
        "grade": 7,
        "chapter": 3,
        "chapter_title": "Generation of Electricity",
        "part": "I",
        "skill_label": "Sources of electricity generation",
        "curriculum_reference": "Ch.3: Sources of electricity generation"
    },
    "G7_C3_ELE_CURRENTS": {
        "grade": 7,
        "chapter": 3,
        "chapter_title": "Generation of Electricity",
        "part": "I",
        "skill_label": "Direct current and alternating current",
        "curriculum_reference": "Ch.3: Direct current and alternating current"
    },
    "G7_C4_WAT_SOLVENT": {
        "grade": 7,
        "chapter": 4,
        "chapter_title": "Functions of Water",
        "part": "I",
        "skill_label": "Water as a solvent and medium of life",
        "curriculum_reference": "Ch.4: Water as a solvent and medium of life"
    },
    "G7_C4_WAT_COOLANT": {
        "grade": 7,
        "chapter": 4,
        "chapter_title": "Functions of Water",
        "part": "I",
        "skill_label": "Water as a coolant",
        "curriculum_reference": "Ch.4: Water as a coolant"
    },
    "G7_C5_ACI_IDENTIF": {
        "grade": 7,
        "chapter": 5,
        "chapter_title": "Acids and Bases",
        "part": "I",
        "skill_label": "Identification of acids and bases",
        "curriculum_reference": "Ch.5: Identification of acids and bases"
    },
    "G7_C5_ACI_INDICAT": {
        "grade": 7,
        "chapter": 5,
        "chapter_title": "Acids and Bases",
        "part": "I",
        "skill_label": "Indicators and neutralization ideas",
        "curriculum_reference": "Ch.5: Indicators and neutralization ideas"
    },
    "G7_C6_ANI_CLASSIF": {
        "grade": 7,
        "chapter": 6,
        "chapter_title": "Animal Diversity",
        "part": "I",
        "skill_label": "Vertebrates, invertebrates, dichotomous keys",
        "curriculum_reference": "Ch.6: Vertebrates, invertebrates, dichotomous keys"
    },
    "G7_C6_ANI_ADAPTAT": {
        "grade": 7,
        "chapter": 6,
        "chapter_title": "Animal Diversity",
        "part": "I",
        "skill_label": "Animal adaptations to environment",
        "curriculum_reference": "Ch.6: Animal adaptations to environment"
    },
    "G7_C7_ENE_FORMS": {
        "grade": 7,
        "chapter": 7,
        "chapter_title": "Forms of Energy and Uses",
        "part": "I",
        "skill_label": "Forms of energy (kinetic, potential, thermal, \u2026)",
        "curriculum_reference": "Ch.7: Forms of energy (kinetic, potential, thermal, \u2026)"
    },
    "G7_C7_ENE_TRANSF": {
        "grade": 7,
        "chapter": 7,
        "chapter_title": "Forms of Energy and Uses",
        "part": "I",
        "skill_label": "Energy transformation and uses",
        "curriculum_reference": "Ch.7: Energy transformation and uses"
    },
    "G7_C8_EAR_STRUCT": {
        "grade": 7,
        "chapter": 8,
        "chapter_title": "The Nature of the Earth",
        "part": "I",
        "skill_label": "Structure of the Earth",
        "curriculum_reference": "Ch.8: Structure of the Earth"
    },
    "G7_C8_EAR_TECTON": {
        "grade": 7,
        "chapter": 8,
        "chapter_title": "The Nature of the Earth",
        "part": "I",
        "skill_label": "Tectonic plates and plate tectonics",
        "curriculum_reference": "Ch.8: Tectonic plates and plate tectonics"
    },
    "G7_C9_LIG_SHADOWS": {
        "grade": 7,
        "chapter": 9,
        "chapter_title": "Light",
        "part": "I",
        "skill_label": "Formation of umbra and penumbra",
        "curriculum_reference": "Ch.9: Formation of umbra and penumbra"
    },
    "G7_C9_LIG_MIRRORS": {
        "grade": 7,
        "chapter": 9,
        "chapter_title": "Light",
        "part": "I",
        "skill_label": "Images in plane and curved mirrors",
        "curriculum_reference": "Ch.9: Images in plane and curved mirrors"
    },
    "G7_C10_MIC_LIGHT": {
        "grade": 7,
        "chapter": 10,
        "chapter_title": "The Correct Use of the Microscope",
        "part": "I",
        "skill_label": "Simple and compound light microscopes",
        "curriculum_reference": "Ch.10: Simple and compound light microscopes"
    },
    "G7_C10_MIC_ELECTR": {
        "grade": 7,
        "chapter": 10,
        "chapter_title": "The Correct Use of the Microscope",
        "part": "I",
        "skill_label": "Electron microscope characteristics",
        "curriculum_reference": "Ch.10: Electron microscope characteristics"
    },
    "G7_C11_SOU_PRODUCE": {
        "grade": 7,
        "chapter": 11,
        "chapter_title": "Sound",
        "part": "II",
        "skill_label": "Production of sound",
        "curriculum_reference": "Ch.11: Production of sound"
    },
    "G7_C11_SOU_PROPAG": {
        "grade": 7,
        "chapter": 11,
        "chapter_title": "Sound",
        "part": "II",
        "skill_label": "Propagation of sound",
        "curriculum_reference": "Ch.11: Propagation of sound"
    },
    "G7_C12_BIO_LEVELS": {
        "grade": 7,
        "chapter": 12,
        "chapter_title": "Biological Processes",
        "part": "II",
        "skill_label": "Organisational levels of life",
        "curriculum_reference": "Ch.12: Organisational levels of life"
    },
    "G7_C12_BIO_SYSTEMS": {
        "grade": 7,
        "chapter": 12,
        "chapter_title": "Biological Processes",
        "part": "II",
        "skill_label": "Systems of the human body",
        "curriculum_reference": "Ch.12: Systems of the human body"
    },
    "G7_C13_ATM_LAYERS": {
        "grade": 7,
        "chapter": 13,
        "chapter_title": "Atmosphere",
        "part": "II",
        "skill_label": "Layers of the atmosphere",
        "curriculum_reference": "Ch.13: Layers of the atmosphere"
    },
    "G7_C13_ATM_AIR": {
        "grade": 7,
        "chapter": 13,
        "chapter_title": "Atmosphere",
        "part": "II",
        "skill_label": "Air and its components",
        "curriculum_reference": "Ch.13: Air and its components"
    },
    "G7_C14_HEA_MEASURE": {
        "grade": 7,
        "chapter": 14,
        "chapter_title": "Heat and Temperature",
        "part": "II",
        "skill_label": "Measuring temperature and thermometers",
        "curriculum_reference": "Ch.14: Measuring temperature and thermometers"
    },
    "G7_C14_HEA_TRANSF": {
        "grade": 7,
        "chapter": 14,
        "chapter_title": "Heat and Temperature",
        "part": "II",
        "skill_label": "Heat transfer and convection applications",
        "curriculum_reference": "Ch.14: Heat transfer and convection applications"
    },
    "G7_C15_SOI_TYPES": {
        "grade": 7,
        "chapter": 15,
        "chapter_title": "Soil",
        "part": "II",
        "skill_label": "Types and composition of soil",
        "curriculum_reference": "Ch.15: Types and composition of soil"
    },
    "G7_C15_SOI_EROSION": {
        "grade": 7,
        "chapter": 15,
        "chapter_title": "Soil",
        "part": "II",
        "skill_label": "Soil erosion",
        "curriculum_reference": "Ch.15: Soil erosion"
    },
    "G7_C16_FOR_DIST": {
        "grade": 7,
        "chapter": 16,
        "chapter_title": "Force and Motion",
        "part": "II",
        "skill_label": "Distance and displacement",
        "curriculum_reference": "Ch.16: Distance and displacement"
    },
    "G7_C16_FOR_FORCE": {
        "grade": 7,
        "chapter": 16,
        "chapter_title": "Force and Motion",
        "part": "II",
        "skill_label": "Force basics",
        "curriculum_reference": "Ch.16: Force basics"
    },
    "G7_C17_NUT_FOOD": {
        "grade": 7,
        "chapter": 17,
        "chapter_title": "Nutrients in Food",
        "part": "II",
        "skill_label": "Food and nutrients",
        "curriculum_reference": "Ch.17: Food and nutrients"
    },
    "G7_C17_NUT_TESTS": {
        "grade": 7,
        "chapter": 17,
        "chapter_title": "Nutrients in Food",
        "part": "II",
        "skill_label": "Food tests to identify nutrients",
        "curriculum_reference": "Ch.17: Food tests to identify nutrients"
    },
    "G7_C18_ROC_KINDS": {
        "grade": 7,
        "chapter": 18,
        "chapter_title": "Minerals and Rocks",
        "part": "II",
        "skill_label": "Features and kinds of rocks and minerals",
        "curriculum_reference": "Ch.18: Features and kinds of rocks and minerals"
    },
    "G7_C18_ROC_CYCLE": {
        "grade": 7,
        "chapter": 18,
        "chapter_title": "Minerals and Rocks",
        "part": "II",
        "skill_label": "Rock weathering and rock cycle",
        "curriculum_reference": "Ch.18: Rock weathering and rock cycle"
    },
    "G7_C19_ENE_RENEW": {
        "grade": 7,
        "chapter": 19,
        "chapter_title": "Sources of Energy",
        "part": "II",
        "skill_label": "Renewable and non-renewable energy sources",
        "curriculum_reference": "Ch.19: Renewable and non-renewable energy sources"
    },
    "G7_C19_ENE_SUSTAIN": {
        "grade": 7,
        "chapter": 19,
        "chapter_title": "Sources of Energy",
        "part": "II",
        "skill_label": "Sustainable usage of energy sources",
        "curriculum_reference": "Ch.19: Sustainable usage of energy sources"
    },
    "G8_C1_MIC_INTRO": {
        "grade": 8,
        "chapter": 1,
        "chapter_title": "Importance of Microorganisms",
        "part": "I",
        "skill_label": "Microorganisms and their diversity",
        "curriculum_reference": "Ch.1: Microorganisms and their diversity"
    },
    "G8_C1_MIC_EFFECTS": {
        "grade": 8,
        "chapter": 1,
        "chapter_title": "Importance of Microorganisms",
        "part": "I",
        "skill_label": "Effects of microorganisms on food and humans",
        "curriculum_reference": "Ch.1: Effects of microorganisms on food and humans"
    },
    "G8_C2_ANI_INVERT": {
        "grade": 8,
        "chapter": 2,
        "chapter_title": "Animal Classification",
        "part": "I",
        "skill_label": "Main invertebrate groups",
        "curriculum_reference": "Ch.2: Main invertebrate groups"
    },
    "G8_C2_ANI_VERT": {
        "grade": 8,
        "chapter": 2,
        "chapter_title": "Animal Classification",
        "part": "I",
        "skill_label": "Main vertebrate groups",
        "curriculum_reference": "Ch.2: Main vertebrate groups"
    },
    "G8_C3_PLA_LEAVES": {
        "grade": 8,
        "chapter": 3,
        "chapter_title": "Diversity and Functions of Plant Parts",
        "part": "I",
        "skill_label": "Diversity and functions of plant leaves",
        "curriculum_reference": "Ch.3: Diversity and functions of plant leaves"
    },
    "G8_C3_PLA_STEMROOT": {
        "grade": 8,
        "chapter": 3,
        "chapter_title": "Diversity and Functions of Plant Parts",
        "part": "I",
        "skill_label": "Diversity and functions of stems and roots",
        "curriculum_reference": "Ch.3: Diversity and functions of stems and roots"
    },
    "G8_C4_MAT_PARTICLE": {
        "grade": 8,
        "chapter": 4,
        "chapter_title": "Properties of Matter",
        "part": "I",
        "skill_label": "Discontinuous nature of matter",
        "curriculum_reference": "Ch.4: Discontinuous nature of matter"
    },
    "G8_C4_MAT_PROPS": {
        "grade": 8,
        "chapter": 4,
        "chapter_title": "Properties of Matter",
        "part": "I",
        "skill_label": "Utilizing physical properties of matter",
        "curriculum_reference": "Ch.4: Utilizing physical properties of matter"
    },
    "G8_C5_SOU_INSTR": {
        "grade": 8,
        "chapter": 5,
        "chapter_title": "Sound",
        "part": "I",
        "skill_label": "Musical instruments and sound production",
        "curriculum_reference": "Ch.5: Musical instruments and sound production"
    },
    "G8_C5_SOU_VIBRATE": {
        "grade": 8,
        "chapter": 5,
        "chapter_title": "Sound",
        "part": "I",
        "skill_label": "Vibration types that produce sound",
        "curriculum_reference": "Ch.5: Vibration types that produce sound"
    },
    "G8_C6_MAG_FIELD": {
        "grade": 8,
        "chapter": 6,
        "chapter_title": "Magnets",
        "part": "I",
        "skill_label": "Magnetic poles, field, and compass",
        "curriculum_reference": "Ch.6: Magnetic poles, field, and compass"
    },
    "G8_C6_MAG_TYPES": {
        "grade": 8,
        "chapter": 6,
        "chapter_title": "Magnets",
        "part": "I",
        "skill_label": "Temporary and permanent magnets",
        "curriculum_reference": "Ch.6: Temporary and permanent magnets"
    },
    "G8_C7_ELE_CURRENT": {
        "grade": 8,
        "chapter": 7,
        "chapter_title": "Measurements Associated with Electricity",
        "part": "I",
        "skill_label": "Electric current and potential difference",
        "curriculum_reference": "Ch.7: Electric current and potential difference"
    },
    "G8_C7_ELE_RESIST": {
        "grade": 8,
        "chapter": 7,
        "chapter_title": "Measurements Associated with Electricity",
        "part": "I",
        "skill_label": "Resistance of a conductor",
        "curriculum_reference": "Ch.7: Resistance of a conductor"
    },
    "G8_C8_CHA_PHYSCHEM": {
        "grade": 8,
        "chapter": 8,
        "chapter_title": "Changes in Matter",
        "part": "I",
        "skill_label": "Physical and chemical changes",
        "curriculum_reference": "Ch.8: Physical and chemical changes"
    },
    "G8_C8_CHA_COMBUST": {
        "grade": 8,
        "chapter": 8,
        "chapter_title": "Changes in Matter",
        "part": "I",
        "skill_label": "Combustion, tarnishing, and neutralisation",
        "curriculum_reference": "Ch.8: Combustion, tarnishing, and neutralisation"
    },
    "G8_C9_HUM_EXCRET": {
        "grade": 8,
        "chapter": 9,
        "chapter_title": "Human Organ Systems",
        "part": "II",
        "skill_label": "Human excretory system",
        "curriculum_reference": "Ch.9: Human excretory system"
    },
    "G8_C9_HUM_NERVSKIN": {
        "grade": 8,
        "chapter": 9,
        "chapter_title": "Human Organ Systems",
        "part": "II",
        "skill_label": "Nervous system and human skin",
        "curriculum_reference": "Ch.9: Nervous system and human skin"
    },
    "G8_C10_ELE_CIRCUITS": {
        "grade": 8,
        "chapter": 10,
        "chapter_title": "Electricity",
        "part": "II",
        "skill_label": "Simple circuits and cell/bulb connections",
        "curriculum_reference": "Ch.10: Simple circuits and cell/bulb connections"
    },
    "G8_C10_ELE_EFFECTS": {
        "grade": 8,
        "chapter": 10,
        "chapter_title": "Electricity",
        "part": "II",
        "skill_label": "Heating, light, magnetic, chemical effects of current",
        "curriculum_reference": "Ch.10: Heating, light, magnetic, chemical effects of current"
    },
    "G8_C11_PHO_PROCESS": {
        "grade": 8,
        "chapter": 11,
        "chapter_title": "Main Biological Processes in Plants",
        "part": "II",
        "skill_label": "Photosynthesis process",
        "curriculum_reference": "Ch.11: Photosynthesis process"
    },
    "G8_C11_PHO_TRANSP": {
        "grade": 8,
        "chapter": 11,
        "chapter_title": "Main Biological Processes in Plants",
        "part": "II",
        "skill_label": "Transportation, transpiration, and guttation",
        "curriculum_reference": "Ch.11: Transportation, transpiration, and guttation"
    },
    "G8_C12_LIF_ANIMAL": {
        "grade": 8,
        "chapter": 12,
        "chapter_title": "Life Cycles of Living Organisms",
        "part": "II",
        "skill_label": "Life cycles of animals",
        "curriculum_reference": "Ch.12: Life cycles of animals"
    },
    "G8_C12_LIF_PLANT": {
        "grade": 8,
        "chapter": 12,
        "chapter_title": "Life Cycles of Living Organisms",
        "part": "II",
        "skill_label": "Life cycles of plants and their importance",
        "curriculum_reference": "Ch.12: Life cycles of plants and their importance"
    },
    "G8_C13_FOO_METHODS": {
        "grade": 8,
        "chapter": 13,
        "chapter_title": "Food Preservation",
        "part": "II",
        "skill_label": "Need and methods of food preservation",
        "curriculum_reference": "Ch.13: Need and methods of food preservation"
    },
    "G8_C13_FOO_LABEL": {
        "grade": 8,
        "chapter": 13,
        "chapter_title": "Food Preservation",
        "part": "II",
        "skill_label": "Advantages of preservation and food labels",
        "curriculum_reference": "Ch.13: Advantages of preservation and food labels"
    },
    "G8_C14_SOL_SYSTEM": {
        "grade": 8,
        "chapter": 14,
        "chapter_title": "Solar System Phenomena",
        "part": "II",
        "skill_label": "The solar system and seasonal/lunar phenomena",
        "curriculum_reference": "Ch.14: The solar system and seasonal/lunar phenomena"
    },
    "G8_C14_SOL_EXPLORE": {
        "grade": 8,
        "chapter": 14,
        "chapter_title": "Solar System Phenomena",
        "part": "II",
        "skill_label": "Exploring the universe, satellites, constellations",
        "curriculum_reference": "Ch.14: Exploring the universe, satellites, constellations"
    },
    "G8_C15_DIS_HYDRO": {
        "grade": 8,
        "chapter": 15,
        "chapter_title": "Natural Disasters",
        "part": "II",
        "skill_label": "Drought, floods, and landslides",
        "curriculum_reference": "Ch.15: Drought, floods, and landslides"
    },
    "G8_C15_DIS_LIGHTNG": {
        "grade": 8,
        "chapter": 15,
        "chapter_title": "Natural Disasters",
        "part": "II",
        "skill_label": "Lightning and thundering",
        "curriculum_reference": "Ch.15: Lightning and thundering"
    },
    "G9_C1_MIC_ENV": {
        "grade": 9,
        "chapter": 1,
        "chapter_title": "Applications of Micro-organisms",
        "part": "I",
        "skill_label": "Micro-organisms, substrates, and environments",
        "curriculum_reference": "Ch.1: Micro-organisms, substrates, and environments"
    },
    "G9_C1_MIC_EFFECTS": {
        "grade": 9,
        "chapter": 1,
        "chapter_title": "Applications of Micro-organisms",
        "part": "I",
        "skill_label": "Effects and applications of micro-organisms",
        "curriculum_reference": "Ch.1: Effects and applications of micro-organisms"
    },
    "G9_C2_SEN_EYE": {
        "grade": 9,
        "chapter": 2,
        "chapter_title": "Eye and Ear",
        "part": "I",
        "skill_label": "Structure and defects of the human eye",
        "curriculum_reference": "Ch.2: Structure and defects of the human eye"
    },
    "G9_C2_SEN_EAR": {
        "grade": 9,
        "chapter": 2,
        "chapter_title": "Eye and Ear",
        "part": "I",
        "skill_label": "Structure and defects of the human ear",
        "curriculum_reference": "Ch.2: Structure and defects of the human ear"
    },
    "G9_C3_MAT_ELEMENTS": {
        "grade": 9,
        "chapter": 3,
        "chapter_title": "Nature and Properties of Matter",
        "part": "I",
        "skill_label": "Elements, compounds, and mixtures",
        "curriculum_reference": "Ch.3: Elements, compounds, and mixtures"
    },
    "G9_C3_MAT_MIXTURES": {
        "grade": 9,
        "chapter": 3,
        "chapter_title": "Nature and Properties of Matter",
        "part": "I",
        "skill_label": "Mixtures and separation ideas",
        "curriculum_reference": "Ch.3: Mixtures and separation ideas"
    },
    "G9_C4_FOR_FORCE": {
        "grade": 9,
        "chapter": 4,
        "chapter_title": "Basic Concepts Associated with Force",
        "part": "I",
        "skill_label": "Force, magnitude, direction, and point of application",
        "curriculum_reference": "Ch.4: Force, magnitude, direction, and point of application"
    },
    "G9_C4_FOR_GRAPH": {
        "grade": 9,
        "chapter": 4,
        "chapter_title": "Basic Concepts Associated with Force",
        "part": "I",
        "skill_label": "Graphical representation of force",
        "curriculum_reference": "Ch.4: Graphical representation of force"
    },
    "G9_C5_PRE_PRESSURE": {
        "grade": 9,
        "chapter": 5,
        "chapter_title": "Pressure Exerted by Solid",
        "part": "I",
        "skill_label": "Pressure and factors affecting pressure",
        "curriculum_reference": "Ch.5: Pressure and factors affecting pressure"
    },
    "G9_C5_PRE_APPLY": {
        "grade": 9,
        "chapter": 5,
        "chapter_title": "Pressure Exerted by Solid",
        "part": "I",
        "skill_label": "Changing pressure factors as needed",
        "curriculum_reference": "Ch.5: Changing pressure factors as needed"
    },
    "G9_C6_CIR_HEART": {
        "grade": 9,
        "chapter": 6,
        "chapter_title": "The Human Circulatory System",
        "part": "I",
        "skill_label": "Structure of the heart; vessels",
        "curriculum_reference": "Ch.6: Structure of the heart; vessels"
    },
    "G9_C6_CIR_BLOOD": {
        "grade": 9,
        "chapter": 6,
        "chapter_title": "The Human Circulatory System",
        "part": "I",
        "skill_label": "Blood components and transfusion",
        "curriculum_reference": "Ch.6: Blood components and transfusion"
    },
    "G9_C7_PGS_INTRO": {
        "grade": 9,
        "chapter": 7,
        "chapter_title": "Plant Growth Substances",
        "part": "I",
        "skill_label": "Introduction to plant growth substances",
        "curriculum_reference": "Ch.7: Introduction to plant growth substances"
    },
    "G9_C7_PGS_ARTIF": {
        "grade": 9,
        "chapter": 7,
        "chapter_title": "Plant Growth Substances",
        "part": "I",
        "skill_label": "Uses of artificial growth substances",
        "curriculum_reference": "Ch.7: Uses of artificial growth substances"
    },
    "G9_C8_MOV_ANIMAL": {
        "grade": 9,
        "chapter": 8,
        "chapter_title": "Support and Movements of Organisms",
        "part": "I",
        "skill_label": "Bones, muscles, joints; animal movement",
        "curriculum_reference": "Ch.8: Bones, muscles, joints; animal movement"
    },
    "G9_C8_MOV_PLANT": {
        "grade": 9,
        "chapter": 8,
        "chapter_title": "Support and Movements of Organisms",
        "part": "I",
        "skill_label": "Support and movements of plants",
        "curriculum_reference": "Ch.8: Support and movements of plants"
    },
    "G9_C9_EVO_ORIGIN": {
        "grade": 9,
        "chapter": 9,
        "chapter_title": "The Evolutionary Process",
        "part": "I",
        "skill_label": "Origin of Earth and life",
        "curriculum_reference": "Ch.9: Origin of Earth and life"
    },
    "G9_C9_EVO_BIODIV": {
        "grade": 9,
        "chapter": 9,
        "chapter_title": "The Evolutionary Process",
        "part": "I",
        "skill_label": "Evolution and importance for biodiversity",
        "curriculum_reference": "Ch.9: Evolution and importance for biodiversity"
    },
    "G9_C10_ELE_LYSIS": {
        "grade": 9,
        "chapter": 10,
        "chapter_title": "Electrolysis",
        "part": "II",
        "skill_label": "Electrolysis and solution changes by current",
        "curriculum_reference": "Ch.10: Electrolysis and solution changes by current"
    },
    "G9_C10_ELE_PLATE": {
        "grade": 9,
        "chapter": 10,
        "chapter_title": "Electrolysis",
        "part": "II",
        "skill_label": "Electroplating",
        "curriculum_reference": "Ch.10: Electroplating"
    },
    "G9_C11_DEN_INTRO": {
        "grade": 9,
        "chapter": 11,
        "chapter_title": "Density",
        "part": "II",
        "skill_label": "Introduction to density and units",
        "curriculum_reference": "Ch.11: Introduction to density and units"
    },
    "G9_C11_DEN_HYDRO": {
        "grade": 9,
        "chapter": 11,
        "chapter_title": "Density",
        "part": "II",
        "skill_label": "Hydrometers",
        "curriculum_reference": "Ch.11: Hydrometers"
    },
    "G9_C12_BIO_INTRO": {
        "grade": 9,
        "chapter": 12,
        "chapter_title": "Bio-diversity",
        "part": "II",
        "skill_label": "Bio-diversity and its importance",
        "curriculum_reference": "Ch.12: Bio-diversity and its importance"
    },
    "G9_C12_BIO_ECO": {
        "grade": 9,
        "chapter": 12,
        "chapter_title": "Bio-diversity",
        "part": "II",
        "skill_label": "Ecosystems, threats, and built vs natural environments",
        "curriculum_reference": "Ch.12: Ecosystems, threats, and built vs natural environments"
    },
    "G9_C13_GRN_CONCEPT": {
        "grade": 9,
        "chapter": 13,
        "chapter_title": "Artificial Environment and Green Concept",
        "part": "II",
        "skill_label": "Artificial environment and green concept",
        "curriculum_reference": "Ch.13: Artificial environment and green concept"
    },
    "G9_C13_GRN_AGRI": {
        "grade": 9,
        "chapter": 13,
        "chapter_title": "Artificial Environment and Green Concept",
        "part": "II",
        "skill_label": "Agricultural and industrial processes (green)",
        "curriculum_reference": "Ch.13: Agricultural and industrial processes (green)"
    },
    "G9_C14_WAV_REFLECT": {
        "grade": 9,
        "chapter": 14,
        "chapter_title": "Reflection and Refraction of Waves",
        "part": "II",
        "skill_label": "Reflection of light and sound",
        "curriculum_reference": "Ch.14: Reflection of light and sound"
    },
    "G9_C14_WAV_REFRACT": {
        "grade": 9,
        "chapter": 14,
        "chapter_title": "Reflection and Refraction of Waves",
        "part": "II",
        "skill_label": "Refraction of light",
        "curriculum_reference": "Ch.14: Refraction of light"
    },
    "G9_C15_MAC_LEVER": {
        "grade": 9,
        "chapter": 15,
        "chapter_title": "Simple Machines",
        "part": "II",
        "skill_label": "Lever and inclined plane",
        "curriculum_reference": "Ch.15: Lever and inclined plane"
    },
    "G9_C15_MAC_PULLEY": {
        "grade": 9,
        "chapter": 15,
        "chapter_title": "Simple Machines",
        "part": "II",
        "skill_label": "Wheel and axle; pulleys",
        "curriculum_reference": "Ch.15: Wheel and axle; pulleys"
    },
    "G9_C16_NANO_INTRO": {
        "grade": 9,
        "chapter": 16,
        "chapter_title": "Nanotechnology and its Applications",
        "part": "II",
        "skill_label": "Nanometer and nanotechnology basics",
        "curriculum_reference": "Ch.16: Nanometer and nanotechnology basics"
    },
    "G9_C16_NANO_APPS": {
        "grade": 9,
        "chapter": 16,
        "chapter_title": "Nanotechnology and its Applications",
        "part": "II",
        "skill_label": "Applications and future of nanotechnology",
        "curriculum_reference": "Ch.16: Applications and future of nanotechnology"
    },
    "G9_C17_LIG_OCCUR": {
        "grade": 9,
        "chapter": 17,
        "chapter_title": "Lightning Accidents",
        "part": "II",
        "skill_label": "How lightning occurs",
        "curriculum_reference": "Ch.17: How lightning occurs"
    },
    "G9_C17_LIG_PREVENT": {
        "grade": 9,
        "chapter": 17,
        "chapter_title": "Lightning Accidents",
        "part": "II",
        "skill_label": "Prevention of lightning accidents",
        "curriculum_reference": "Ch.17: Prevention of lightning accidents"
    },
    "G9_C18_DIS_TYPES": {
        "grade": 9,
        "chapter": 18,
        "chapter_title": "Natural Disasters",
        "part": "II",
        "skill_label": "Cyclones, earthquakes, tsunami, wild fires",
        "curriculum_reference": "Ch.18: Cyclones, earthquakes, tsunami, wild fires"
    },
    "G9_C18_DIS_WARMING": {
        "grade": 9,
        "chapter": 18,
        "chapter_title": "Natural Disasters",
        "part": "II",
        "skill_label": "Global warming and disasters",
        "curriculum_reference": "Ch.18: Global warming and disasters"
    },
    "G9_C19_RES_WATER": {
        "grade": 9,
        "chapter": 19,
        "chapter_title": "Sustainable Use of Natural Resources",
        "part": "II",
        "skill_label": "Sustainable use of water",
        "curriculum_reference": "Ch.19: Sustainable use of water"
    },
    "G9_C19_RES_MINERAL": {
        "grade": 9,
        "chapter": 19,
        "chapter_title": "Sustainable Use of Natural Resources",
        "part": "II",
        "skill_label": "Sustainable use of minerals, rocks, and trees",
        "curriculum_reference": "Ch.19: Sustainable use of minerals, rocks, and trees"
    }
}

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "G6_C1_ORG_CHARS": [
        "characteristics of organisms",
        "living",
        "growth",
        "nutrition",
        "reproduction",
        "respiration",
        "excretion",
        "sensitivity",
        "movement",
        "alive"
    ],
    "G6_C1_ORG_DIFF": [
        "plants and animals",
        "plant",
        "animal",
        "differences",
        "photosynthesis",
        "locomotion",
        "chlorophyll",
        "autotroph"
    ],
    "G6_C2_MAT_STATES": [
        "states of matter",
        "solid",
        "liquid",
        "gas",
        "particle",
        "melting",
        "freezing",
        "evaporation",
        "condensation"
    ],
    "G6_C2_MAT_PROPS": [
        "properties of solid",
        "hardness",
        "malleability",
        "ductility",
        "density",
        "transparency",
        "absorbency",
        "conductivity"
    ],
    "G6_C3_WAT_STATES": [
        "water",
        "states of water",
        "fresh water",
        "salt water",
        "salinity",
        "availability of water",
        "ice",
        "steam",
        "vapour"
    ],
    "G6_C3_WAT_IMPORT": [
        "importance of water",
        "conserve water",
        "limited resource",
        "water cycle",
        "drinking water",
        "drought"
    ],
    "G6_C4_ENE_SOURCES": [
        "energy sources",
        "energy",
        "fuel",
        "solar",
        "wind",
        "electric",
        "applications of energy",
        "day to day energy"
    ],
    "G6_C4_ENE_FORMS": [
        "forms of energy",
        "heat energy",
        "light energy",
        "sound energy",
        "mechanical energy",
        "chemical energy"
    ],
    "G6_C5_LIG_SEE": [
        "light",
        "vision",
        "how can we see",
        "source of light",
        "transparent",
        "opaque",
        "translucent",
        "transmission of light"
    ],
    "G6_C5_LIG_RAYS": [
        "light ray",
        "light beam",
        "reflection everyday",
        "applications of light",
        "shadow",
        "mirror"
    ],
    "G6_C6_SOU_PRODUCE": [
        "sound",
        "hearing",
        "producing sound",
        "vibration",
        "ear",
        "listen"
    ],
    "G6_C6_SOU_DIVERSE": [
        "music",
        "noise",
        "diversity of sounds",
        "pitch",
        "loudness",
        "equipment to produce sound"
    ],
    "G6_C7_MAG_POLES": [
        "magnet",
        "magnetic pole",
        "north pole",
        "south pole",
        "types of magnets",
        "behaviour of a magnet",
        "bar magnet"
    ],
    "G6_C7_MAG_FORCES": [
        "magnetic force",
        "attraction",
        "repulsion",
        "like poles",
        "unlike poles",
        "magnetic field basic"
    ],
    "G6_C8_ELE_CIRCUITS": [
        "electric circuit",
        "circuit",
        "cell",
        "battery",
        "bulb",
        "switch",
        "generating electricity",
        "wire",
        "series",
        "parallel"
    ],
    "G6_C8_ELE_CONDINS": [
        "conductor",
        "insulator",
        "conducting",
        "insulating",
        "metal",
        "plastic",
        "rubber",
        "conservation of electricity",
        "electrical safety"
    ],
    "G6_C9_HEA_GEN": [
        "heat",
        "heat generation",
        "temperature basic",
        "effects of heat",
        "hot",
        "cold",
        "expand heat"
    ],
    "G6_C9_HEA_ENV": [
        "heat environment",
        "global warming basic",
        "heat pollution",
        "effects of heat to the environment"
    ],
    "G6_C10_FOO_INTER": [
        "food",
        "food chain",
        "food web",
        "producer",
        "consumer",
        "decomposer",
        "interaction food"
    ],
    "G6_C10_FOO_NUTR": [
        "nutrition",
        "herbivore",
        "carnivore",
        "omnivore",
        "feeding",
        "energy flow food"
    ],
    "G6_C11_WEA_WEATHER": [
        "weather",
        "climate",
        "rainfall",
        "temperature weather",
        "humidity",
        "weather apparatus",
        "rain gauge"
    ],
    "G6_C11_WEA_DISASTER": [
        "natural disaster",
        "flood",
        "drought",
        "climatic change",
        "storm",
        "weather disaster"
    ],
    "G7_C1_PLA_DIVER": [
        "plant diversity",
        "morphological",
        "flowering plant",
        "root",
        "stem",
        "leaf",
        "flower parts",
        "diversity of plant parts"
    ],
    "G7_C1_PLA_CLASSIF": [
        "monocot",
        "dicot",
        "monocotyledonous",
        "dicotyledonous",
        "cotyledon",
        "plant classification"
    ],
    "G7_C2_STA_CHARGES": [
        "static electricity",
        "charging",
        "static charge",
        "positive charge",
        "negative charge",
        "friction charging",
        "electrostatic"
    ],
    "G7_C2_STA_CAPACIT": [
        "capacitor",
        "capacitance",
        "store charge",
        "static phenomena",
        "electroscope"
    ],
    "G7_C3_ELE_SOURCES": [
        "generation of electricity",
        "sources of electricity",
        "hydro power",
        "thermal power",
        "solar electricity",
        "wind turbine",
        "generator"
    ],
    "G7_C3_ELE_CURRENTS": [
        "direct current",
        "alternating current",
        "dc",
        "ac",
        "electric current",
        "ammeter"
    ],
    "G7_C4_WAT_SOLVENT": [
        "water as solvent",
        "universal solvent",
        "dissolve",
        "solute",
        "solution",
        "medium of life",
        "water functions"
    ],
    "G7_C4_WAT_COOLANT": [
        "coolant",
        "cooling",
        "heat capacity of water",
        "thermal properties of water"
    ],
    "G7_C5_ACI_IDENTIF": [
        "acid",
        "base",
        "alkali",
        "identification of acids",
        "litmus",
        "laboratory acid",
        "home acid"
    ],
    "G7_C5_ACI_INDICAT": [
        "indicator",
        "ph",
        "neutralization",
        "universal indicator",
        "acid base reaction"
    ],
    "G7_C6_ANI_CLASSIF": [
        "vertebrate",
        "invertebrate",
        "animal classification",
        "dichotomous key",
        "animal diversity"
    ],
    "G7_C6_ANI_ADAPTAT": [
        "adaptation",
        "animal adaptation",
        "habitat",
        "camouflage",
        "survive environment"
    ],
    "G7_C7_ENE_FORMS": [
        "forms of energy",
        "kinetic energy",
        "potential energy",
        "electrical energy",
        "sound energy",
        "light energy",
        "thermal energy",
        "chemical energy"
    ],
    "G7_C7_ENE_TRANSF": [
        "energy transformation",
        "energy conversion",
        "uses of energy",
        "energy transfer"
    ],
    "G7_C8_EAR_STRUCT": [
        "structure of the earth",
        "crust",
        "mantle",
        "core",
        "earth layers",
        "internal structure"
    ],
    "G7_C8_EAR_TECTON": [
        "tectonic",
        "plate tectonics",
        "plate movement",
        "earthquake basic",
        "continental plate"
    ],
    "G7_C9_LIG_SHADOWS": [
        "umbra",
        "penumbra",
        "shadow",
        "formation of shadows",
        "light shadow"
    ],
    "G7_C9_LIG_MIRRORS": [
        "plane mirror",
        "curved mirror",
        "reflection",
        "image formation",
        "concave mirror",
        "convex mirror"
    ],
    "G7_C10_MIC_LIGHT": [
        "microscope",
        "compound microscope",
        "simple microscope",
        "magnification",
        "resolving power",
        "objective lens"
    ],
    "G7_C10_MIC_ELECTR": [
        "electron microscope",
        "resolution electron",
        "sem",
        "tem",
        "high resolution microscope"
    ],
    "G7_C11_SOU_PRODUCE": [
        "production of sound",
        "vibration sound",
        "sound source",
        "how sound is produced"
    ],
    "G7_C11_SOU_PROPAG": [
        "propagation of sound",
        "sound medium",
        "sound wave travel",
        "echo basic",
        "sound through air"
    ],
    "G7_C12_BIO_LEVELS": [
        "organisational levels",
        "cell",
        "tissue",
        "organ",
        "system",
        "levels of organisation"
    ],
    "G7_C12_BIO_SYSTEMS": [
        "human body systems",
        "digestive system intro",
        "respiratory system intro",
        "circulatory intro",
        "biological processes body"
    ],
    "G7_C13_ATM_LAYERS": [
        "atmosphere",
        "troposphere",
        "stratosphere",
        "layers of atmosphere",
        "atmospheric layers"
    ],
    "G7_C13_ATM_AIR": [
        "air",
        "oxygen",
        "nitrogen",
        "carbon dioxide air",
        "composition of air",
        "components of air"
    ],
    "G7_C14_HEA_MEASURE": [
        "temperature",
        "thermometer",
        "measuring temperature",
        "celsius",
        "heat and temperature"
    ],
    "G7_C14_HEA_TRANSF": [
        "heat transfer",
        "conduction",
        "convection",
        "radiation heat",
        "convectional currents"
    ],
    "G7_C15_SOI_TYPES": [
        "soil",
        "types of soil",
        "sand",
        "clay",
        "loam",
        "composition of soil",
        "soil particles"
    ],
    "G7_C15_SOI_EROSION": [
        "soil erosion",
        "erode soil",
        "conservation of soil",
        "wash away soil"
    ],
    "G7_C16_FOR_DIST": [
        "distance",
        "displacement",
        "motion",
        "position",
        "path length"
    ],
    "G7_C16_FOR_FORCE": [
        "force",
        "push",
        "pull",
        "newton basic",
        "effect of force",
        "force and motion"
    ],
    "G7_C17_NUT_FOOD": [
        "nutrients",
        "carbohydrate",
        "protein",
        "fat",
        "vitamin",
        "mineral food",
        "balanced diet"
    ],
    "G7_C17_NUT_TESTS": [
        "food test",
        "iodine test",
        "biuret",
        "sudan",
        "identify nutrients",
        "food sample test"
    ],
    "G7_C18_ROC_KINDS": [
        "rock",
        "mineral",
        "igneous",
        "sedimentary",
        "metamorphic",
        "features of minerals"
    ],
    "G7_C18_ROC_CYCLE": [
        "rock cycle",
        "weathering",
        "rock weathering",
        "erosion rocks"
    ],
    "G7_C19_ENE_RENEW": [
        "renewable",
        "non-renewable",
        "fossil fuel",
        "solar energy",
        "wind energy",
        "sources of energy",
        "sustainable energy"
    ],
    "G7_C19_ENE_SUSTAIN": [
        "sustainable energy",
        "energy conservation",
        "efficient use of energy",
        "save energy"
    ],
    "G8_C1_MIC_INTRO": [
        "microorganism",
        "bacteria",
        "yeast",
        "fungi",
        "protozoa",
        "algae micro",
        "microscopic organisms"
    ],
    "G8_C1_MIC_EFFECTS": [
        "spoilage",
        "food spoilage",
        "microbes on food",
        "pathogen",
        "effects of microorganisms",
        "useful microorganisms"
    ],
    "G8_C2_ANI_INVERT": [
        "invertebrate",
        "arthropod",
        "mollusc",
        "annelid",
        "cnidarian",
        "invertebrate groups"
    ],
    "G8_C2_ANI_VERT": [
        "vertebrate",
        "fish",
        "amphibian",
        "reptile",
        "bird",
        "mammal",
        "vertebrate groups"
    ],
    "G8_C3_PLA_LEAVES": [
        "leaf",
        "leaves",
        "functions of leaves",
        "photosynthesis leaf",
        "leaf diversity"
    ],
    "G8_C3_PLA_STEMROOT": [
        "stem",
        "root",
        "functions of stem",
        "functions of root",
        "plant parts",
        "storage root"
    ],
    "G8_C4_MAT_PARTICLE": [
        "particle nature",
        "discontinuous nature",
        "atoms and molecules intro",
        "matter particles",
        "spaces between particles"
    ],
    "G8_C4_MAT_PROPS": [
        "physical properties",
        "density basic",
        "conductivity",
        "solubility",
        "hardness property",
        "using properties of matter"
    ],
    "G8_C5_SOU_INSTR": [
        "musical instrument",
        "vibrating membrane",
        "air column",
        "string instrument",
        "sound instrument",
        "music sound"
    ],
    "G8_C5_SOU_VIBRATE": [
        "vibration",
        "vibrate string",
        "vibrate air",
        "produce sound instrument",
        "pitch instrument"
    ],
    "G8_C6_MAG_FIELD": [
        "magnetic field",
        "compass",
        "geomagnetism",
        "poles of a magnet",
        "magnetic lines"
    ],
    "G8_C6_MAG_TYPES": [
        "temporary magnet",
        "permanent magnet",
        "electromagnet intro",
        "magnet types grade8"
    ],
    "G8_C7_ELE_CURRENT": [
        "electric current",
        "potential difference",
        "voltage",
        "ammeter",
        "voltmeter",
        "measurements electricity"
    ],
    "G8_C7_ELE_RESIST": [
        "resistance",
        "conductor resistance",
        "ohm",
        "resistor",
        "factors affecting resistance"
    ],
    "G8_C8_CHA_PHYSCHEM": [
        "physical change",
        "chemical change",
        "change of state",
        "physical vs chemical"
    ],
    "G8_C8_CHA_COMBUST": [
        "combustion",
        "burning",
        "tarnishing",
        "neutralisation",
        "rust",
        "chemical changes burning"
    ],
    "G8_C9_HUM_EXCRET": [
        "excretory",
        "excretion",
        "kidney",
        "urine",
        "urea",
        "sweat",
        "excretory products"
    ],
    "G8_C9_HUM_NERVSKIN": [
        "nervous system",
        "neuron",
        "brain",
        "spinal cord",
        "skin",
        "sense organ skin"
    ],
    "G8_C10_ELE_CIRCUITS": [
        "simple electric circuit",
        "series parallel grade8",
        "connecting cells",
        "connecting bulbs",
        "circuit components"
    ],
    "G8_C10_ELE_EFFECTS": [
        "heating effect",
        "light effect current",
        "magnetic effect current",
        "chemical effect",
        "household electrical",
        "current controlling"
    ],
    "G8_C11_PHO_PROCESS": [
        "photosynthesis",
        "chlorophyll",
        "glucose",
        "carbon dioxide plant",
        "oxygen plant",
        "raw materials photosynthesis"
    ],
    "G8_C11_PHO_TRANSP": [
        "transportation plant",
        "xylem",
        "phloem",
        "transpiration",
        "guttation",
        "water transport plant"
    ],
    "G8_C12_LIF_ANIMAL": [
        "life cycle animal",
        "metamorphosis",
        "egg larva pupa",
        "life stages animal"
    ],
    "G8_C12_LIF_PLANT": [
        "life cycle plant",
        "seed germination",
        "pollination",
        "life stages plant",
        "importance of life cycles"
    ],
    "G8_C13_FOO_METHODS": [
        "food preservation",
        "preserve food",
        "drying food",
        "refrigeration",
        "canning",
        "food preservative"
    ],
    "G8_C13_FOO_LABEL": [
        "food label",
        "expiry date",
        "preservative advantages",
        "disadvantages of preservation"
    ],
    "G8_C14_SOL_SYSTEM": [
        "solar system",
        "planet",
        "sun",
        "moon",
        "seasons",
        "phases of moon",
        "seasonal changes"
    ],
    "G8_C14_SOL_EXPLORE": [
        "artificial satellite",
        "constellation",
        "universe",
        "space exploration",
        "astronomy basic"
    ],
    "G8_C15_DIS_HYDRO": [
        "drought",
        "flood",
        "landslide",
        "earth slip",
        "natural disaster"
    ],
    "G8_C15_DIS_LIGHTNG": [
        "lightning",
        "thunder",
        "thunderstorm",
        "lightning safety grade8"
    ],
    "G9_C1_MIC_ENV": [
        "micro-organisms",
        "microorganisms applications",
        "substrates",
        "environments of microbes"
    ],
    "G9_C1_MIC_EFFECTS": [
        "useful microbes",
        "harmful microbes",
        "fermentation",
        "applications of microorganisms",
        "biotechnology basic"
    ],
    "G9_C2_SEN_EYE": [
        "eye",
        "vision",
        "retina",
        "lens eye",
        "defects of vision",
        "myopia",
        "hypermetropia",
        "eye disease"
    ],
    "G9_C2_SEN_EAR": [
        "ear",
        "hearing",
        "eardrum",
        "cochlea",
        "defects of ear",
        "auditory"
    ],
    "G9_C3_MAT_ELEMENTS": [
        "element",
        "compound",
        "mixture",
        "chemical symbol",
        "properties of matter grade9",
        "nature of matter"
    ],
    "G9_C3_MAT_MIXTURES": [
        "mixture",
        "homogeneous",
        "heterogeneous",
        "separate mixture",
        "solution mixture"
    ],
    "G9_C4_FOR_FORCE": [
        "force",
        "magnitude of force",
        "direction of force",
        "point of application",
        "newton",
        "graphical force"
    ],
    "G9_C4_FOR_GRAPH": [
        "force diagram",
        "vector force",
        "arrow force",
        "represent force"
    ],
    "G9_C5_PRE_PRESSURE": [
        "pressure",
        "force area",
        "factors affecting pressure",
        "pascal",
        "unit of pressure"
    ],
    "G9_C5_PRE_APPLY": [
        "increase pressure",
        "decrease pressure",
        "sharp knife pressure",
        "applications of pressure"
    ],
    "G9_C6_CIR_HEART": [
        "circulatory",
        "heart",
        "artery",
        "vein",
        "capillary",
        "blood vessel"
    ],
    "G9_C6_CIR_BLOOD": [
        "blood",
        "red blood cell",
        "white blood cell",
        "plasma",
        "platelets",
        "blood transfusion",
        "blood group"
    ],
    "G9_C7_PGS_INTRO": [
        "plant growth substance",
        "hormone plant",
        "auxin",
        "gibberellin",
        "cytokinin",
        "plant hormone"
    ],
    "G9_C7_PGS_ARTIF": [
        "artificial growth substance",
        "weedicide",
        "rooting hormone",
        "plant growth regulator"
    ],
    "G9_C8_MOV_ANIMAL": [
        "bone",
        "muscle",
        "joint",
        "skeleton",
        "movement animal",
        "support animals"
    ],
    "G9_C8_MOV_PLANT": [
        "tropism",
        "plant movement",
        "turgor",
        "support plants",
        "phototropism"
    ],
    "G9_C9_EVO_ORIGIN": [
        "origin of earth",
        "origin of life",
        "evolution intro",
        "evolutionary process"
    ],
    "G9_C9_EVO_BIODIV": [
        "evolution",
        "biodiversity evolution",
        "natural selection intro",
        "variation species"
    ],
    "G9_C10_ELE_LYSIS": [
        "electrolysis",
        "electrolyte",
        "electrode",
        "anode",
        "cathode",
        "electric current solution"
    ],
    "G9_C10_ELE_PLATE": [
        "electroplating",
        "plating metal",
        "coat metal electrically"
    ],
    "G9_C11_DEN_INTRO": [
        "density",
        "mass volume",
        "unit of density",
        "kg per m3",
        "relative density intro"
    ],
    "G9_C11_DEN_HYDRO": [
        "hydrometer",
        "measure density liquid",
        "floating densitometer"
    ],
    "G9_C12_BIO_INTRO": [
        "biodiversity",
        "bio-diversity",
        "species diversity",
        "importance of biodiversity"
    ],
    "G9_C12_BIO_ECO": [
        "ecosystem",
        "threats to biodiversity",
        "natural ecosystem",
        "built environment",
        "habitat loss"
    ],
    "G9_C13_GRN_CONCEPT": [
        "green concept",
        "artificial environment",
        "sustainable living",
        "environment friendly"
    ],
    "G9_C13_GRN_AGRI": [
        "agricultural process",
        "industrial process",
        "green agriculture",
        "eco friendly industry"
    ],
    "G9_C14_WAV_REFLECT": [
        "reflection of light",
        "reflection of sound",
        "echo",
        "mirror reflection",
        "wave reflection"
    ],
    "G9_C14_WAV_REFRACT": [
        "refraction",
        "bending of light",
        "refractive index",
        "lens light",
        "critical angle",
        "total internal reflection"
    ],
    "G9_C15_MAC_LEVER": [
        "lever",
        "inclined plane",
        "simple machine",
        "mechanical advantage",
        "load effort"
    ],
    "G9_C15_MAC_PULLEY": [
        "pulley",
        "wheel and axle",
        "movable pulley",
        "fixed pulley",
        "simple machines pulley"
    ],
    "G9_C16_NANO_INTRO": [
        "nanotechnology",
        "nanometer",
        "nano scale",
        "nanoparticle"
    ],
    "G9_C16_NANO_APPS": [
        "applications of nanotechnology",
        "nano medicine",
        "nano materials",
        "future nanotechnology"
    ],
    "G9_C17_LIG_OCCUR": [
        "lightning occurs",
        "thunder cloud",
        "static discharge lightning",
        "lightning formation"
    ],
    "G9_C17_LIG_PREVENT": [
        "lightning safety",
        "lightning conductor",
        "prevent lightning",
        "lightning accident"
    ],
    "G9_C18_DIS_TYPES": [
        "cyclone",
        "earthquake",
        "tsunami",
        "wild fire",
        "natural disaster grade9"
    ],
    "G9_C18_DIS_WARMING": [
        "global warming",
        "climate disaster",
        "greenhouse",
        "relationship global warming disasters"
    ],
    "G9_C19_RES_WATER": [
        "sustainable water",
        "water resources",
        "conserve water resources",
        "natural resources water"
    ],
    "G9_C19_RES_MINERAL": [
        "sustainable minerals",
        "rocks resources",
        "trees conservation",
        "natural resources trees",
        "sustainable use"
    ]
}

TOPIC_QUERY_BOOST: dict[str, str] = {
    "G6_C1_ORG_CHARS": "Grade 6 Chapter 1 (Wonders of the Living World). Characteristics of organisms.",
    "G6_C1_ORG_DIFF": "Grade 6 Chapter 1 (Wonders of the Living World). Differences between plants and animals.",
    "G6_C2_MAT_STATES": "Grade 6 Chapter 2 (Things Around Us). States of matter.",
    "G6_C2_MAT_PROPS": "Grade 6 Chapter 2 (Things Around Us). Specific properties of solid matter.",
    "G6_C3_WAT_STATES": "Grade 6 Chapter 3 (Water as a Natural Resource). States and types of water.",
    "G6_C3_WAT_IMPORT": "Grade 6 Chapter 3 (Water as a Natural Resource). Importance of water and conservation.",
    "G6_C4_ENE_SOURCES": "Grade 6 Chapter 4 (Energy in Day to Day Life). Energy sources and their applications.",
    "G6_C4_ENE_FORMS": "Grade 6 Chapter 4 (Energy in Day to Day Life). Forms of energy in daily life.",
    "G6_C5_LIG_SEE": "Grade 6 Chapter 5 (Light and Vision). How we see; sources and transmission of light.",
    "G6_C5_LIG_RAYS": "Grade 6 Chapter 5 (Light and Vision). Light rays, beams, and applications.",
    "G6_C6_SOU_PRODUCE": "Grade 6 Chapter 6 (Sound and Hearing). Producing and hearing sounds.",
    "G6_C6_SOU_DIVERSE": "Grade 6 Chapter 6 (Sound and Hearing). Diversity of sounds; music and noise.",
    "G6_C7_MAG_POLES": "Grade 6 Chapter 7 (Magnets). Magnetic poles, types, and behaviour.",
    "G6_C7_MAG_FORCES": "Grade 6 Chapter 7 (Magnets). Magnetic interactions and forces.",
    "G6_C8_ELE_CIRCUITS": "Grade 6 Chapter 8 (Electricity for a Comfortable Life). Preparation of circuits and generating electricity.",
    "G6_C8_ELE_CONDINS": "Grade 6 Chapter 8 (Electricity for a Comfortable Life). Conductors and insulators; safety.",
    "G6_C9_HEA_GEN": "Grade 6 Chapter 9 (Heat and Its Effects). Heat generation and effects.",
    "G6_C9_HEA_ENV": "Grade 6 Chapter 9 (Heat and Its Effects). Effects of heat on the environment.",
    "G6_C10_FOO_INTER": "Grade 6 Chapter 10 (Food Related Interactions). Food related interactions in ecosystems.",
    "G6_C10_FOO_NUTR": "Grade 6 Chapter 10 (Food Related Interactions). Nutrition relationships among organisms.",
    "G6_C11_WEA_WEATHER": "Grade 6 Chapter 11 (Weather and Climate). Weather, climate, and measurement.",
    "G6_C11_WEA_DISASTER": "Grade 6 Chapter 11 (Weather and Climate). Natural disasters from climatic changes.",
    "G7_C1_PLA_DIVER": "Grade 7 Chapter 1 (Plant Diversity). Morphological features and plant diversity.",
    "G7_C1_PLA_CLASSIF": "Grade 7 Chapter 1 (Plant Diversity). Monocotyledonous and dicotyledonous plants.",
    "G7_C2_STA_CHARGES": "Grade 7 Chapter 2 (Static Electricity). Charging objects and types of static charge.",
    "G7_C2_STA_CAPACIT": "Grade 7 Chapter 2 (Static Electricity). Capacitors and static electricity phenomena.",
    "G7_C3_ELE_SOURCES": "Grade 7 Chapter 3 (Generation of Electricity). Sources of electricity generation.",
    "G7_C3_ELE_CURRENTS": "Grade 7 Chapter 3 (Generation of Electricity). Direct current and alternating current.",
    "G7_C4_WAT_SOLVENT": "Grade 7 Chapter 4 (Functions of Water). Water as a solvent and medium of life.",
    "G7_C4_WAT_COOLANT": "Grade 7 Chapter 4 (Functions of Water). Water as a coolant.",
    "G7_C5_ACI_IDENTIF": "Grade 7 Chapter 5 (Acids and Bases). Identification of acids and bases.",
    "G7_C5_ACI_INDICAT": "Grade 7 Chapter 5 (Acids and Bases). Indicators and neutralization ideas.",
    "G7_C6_ANI_CLASSIF": "Grade 7 Chapter 6 (Animal Diversity). Vertebrates, invertebrates, dichotomous keys.",
    "G7_C6_ANI_ADAPTAT": "Grade 7 Chapter 6 (Animal Diversity). Animal adaptations to environment.",
    "G7_C7_ENE_FORMS": "Grade 7 Chapter 7 (Forms of Energy and Uses). Forms of energy (kinetic, potential, thermal, \u2026).",
    "G7_C7_ENE_TRANSF": "Grade 7 Chapter 7 (Forms of Energy and Uses). Energy transformation and uses.",
    "G7_C8_EAR_STRUCT": "Grade 7 Chapter 8 (The Nature of the Earth). Structure of the Earth.",
    "G7_C8_EAR_TECTON": "Grade 7 Chapter 8 (The Nature of the Earth). Tectonic plates and plate tectonics.",
    "G7_C9_LIG_SHADOWS": "Grade 7 Chapter 9 (Light). Formation of umbra and penumbra.",
    "G7_C9_LIG_MIRRORS": "Grade 7 Chapter 9 (Light). Images in plane and curved mirrors.",
    "G7_C10_MIC_LIGHT": "Grade 7 Chapter 10 (The Correct Use of the Microscope). Simple and compound light microscopes.",
    "G7_C10_MIC_ELECTR": "Grade 7 Chapter 10 (The Correct Use of the Microscope). Electron microscope characteristics.",
    "G7_C11_SOU_PRODUCE": "Grade 7 Chapter 11 (Sound). Production of sound.",
    "G7_C11_SOU_PROPAG": "Grade 7 Chapter 11 (Sound). Propagation of sound.",
    "G7_C12_BIO_LEVELS": "Grade 7 Chapter 12 (Biological Processes). Organisational levels of life.",
    "G7_C12_BIO_SYSTEMS": "Grade 7 Chapter 12 (Biological Processes). Systems of the human body.",
    "G7_C13_ATM_LAYERS": "Grade 7 Chapter 13 (Atmosphere). Layers of the atmosphere.",
    "G7_C13_ATM_AIR": "Grade 7 Chapter 13 (Atmosphere). Air and its components.",
    "G7_C14_HEA_MEASURE": "Grade 7 Chapter 14 (Heat and Temperature). Measuring temperature and thermometers.",
    "G7_C14_HEA_TRANSF": "Grade 7 Chapter 14 (Heat and Temperature). Heat transfer and convection applications.",
    "G7_C15_SOI_TYPES": "Grade 7 Chapter 15 (Soil). Types and composition of soil.",
    "G7_C15_SOI_EROSION": "Grade 7 Chapter 15 (Soil). Soil erosion.",
    "G7_C16_FOR_DIST": "Grade 7 Chapter 16 (Force and Motion). Distance and displacement.",
    "G7_C16_FOR_FORCE": "Grade 7 Chapter 16 (Force and Motion). Force basics.",
    "G7_C17_NUT_FOOD": "Grade 7 Chapter 17 (Nutrients in Food). Food and nutrients.",
    "G7_C17_NUT_TESTS": "Grade 7 Chapter 17 (Nutrients in Food). Food tests to identify nutrients.",
    "G7_C18_ROC_KINDS": "Grade 7 Chapter 18 (Minerals and Rocks). Features and kinds of rocks and minerals.",
    "G7_C18_ROC_CYCLE": "Grade 7 Chapter 18 (Minerals and Rocks). Rock weathering and rock cycle.",
    "G7_C19_ENE_RENEW": "Grade 7 Chapter 19 (Sources of Energy). Renewable and non-renewable energy sources.",
    "G7_C19_ENE_SUSTAIN": "Grade 7 Chapter 19 (Sources of Energy). Sustainable usage of energy sources.",
    "G8_C1_MIC_INTRO": "Grade 8 Chapter 1 (Importance of Microorganisms). Microorganisms and their diversity.",
    "G8_C1_MIC_EFFECTS": "Grade 8 Chapter 1 (Importance of Microorganisms). Effects of microorganisms on food and humans.",
    "G8_C2_ANI_INVERT": "Grade 8 Chapter 2 (Animal Classification). Main invertebrate groups.",
    "G8_C2_ANI_VERT": "Grade 8 Chapter 2 (Animal Classification). Main vertebrate groups.",
    "G8_C3_PLA_LEAVES": "Grade 8 Chapter 3 (Diversity and Functions of Plant Parts). Diversity and functions of plant leaves.",
    "G8_C3_PLA_STEMROOT": "Grade 8 Chapter 3 (Diversity and Functions of Plant Parts). Diversity and functions of stems and roots.",
    "G8_C4_MAT_PARTICLE": "Grade 8 Chapter 4 (Properties of Matter). Discontinuous nature of matter.",
    "G8_C4_MAT_PROPS": "Grade 8 Chapter 4 (Properties of Matter). Utilizing physical properties of matter.",
    "G8_C5_SOU_INSTR": "Grade 8 Chapter 5 (Sound). Musical instruments and sound production.",
    "G8_C5_SOU_VIBRATE": "Grade 8 Chapter 5 (Sound). Vibration types that produce sound.",
    "G8_C6_MAG_FIELD": "Grade 8 Chapter 6 (Magnets). Magnetic poles, field, and compass.",
    "G8_C6_MAG_TYPES": "Grade 8 Chapter 6 (Magnets). Temporary and permanent magnets.",
    "G8_C7_ELE_CURRENT": "Grade 8 Chapter 7 (Measurements Associated with Electricity). Electric current and potential difference.",
    "G8_C7_ELE_RESIST": "Grade 8 Chapter 7 (Measurements Associated with Electricity). Resistance of a conductor.",
    "G8_C8_CHA_PHYSCHEM": "Grade 8 Chapter 8 (Changes in Matter). Physical and chemical changes.",
    "G8_C8_CHA_COMBUST": "Grade 8 Chapter 8 (Changes in Matter). Combustion, tarnishing, and neutralisation.",
    "G8_C9_HUM_EXCRET": "Grade 8 Chapter 9 (Human Organ Systems). Human excretory system.",
    "G8_C9_HUM_NERVSKIN": "Grade 8 Chapter 9 (Human Organ Systems). Nervous system and human skin.",
    "G8_C10_ELE_CIRCUITS": "Grade 8 Chapter 10 (Electricity). Simple circuits and cell/bulb connections.",
    "G8_C10_ELE_EFFECTS": "Grade 8 Chapter 10 (Electricity). Heating, light, magnetic, chemical effects of current.",
    "G8_C11_PHO_PROCESS": "Grade 8 Chapter 11 (Main Biological Processes in Plants). Photosynthesis process.",
    "G8_C11_PHO_TRANSP": "Grade 8 Chapter 11 (Main Biological Processes in Plants). Transportation, transpiration, and guttation.",
    "G8_C12_LIF_ANIMAL": "Grade 8 Chapter 12 (Life Cycles of Living Organisms). Life cycles of animals.",
    "G8_C12_LIF_PLANT": "Grade 8 Chapter 12 (Life Cycles of Living Organisms). Life cycles of plants and their importance.",
    "G8_C13_FOO_METHODS": "Grade 8 Chapter 13 (Food Preservation). Need and methods of food preservation.",
    "G8_C13_FOO_LABEL": "Grade 8 Chapter 13 (Food Preservation). Advantages of preservation and food labels.",
    "G8_C14_SOL_SYSTEM": "Grade 8 Chapter 14 (Solar System Phenomena). The solar system and seasonal/lunar phenomena.",
    "G8_C14_SOL_EXPLORE": "Grade 8 Chapter 14 (Solar System Phenomena). Exploring the universe, satellites, constellations.",
    "G8_C15_DIS_HYDRO": "Grade 8 Chapter 15 (Natural Disasters). Drought, floods, and landslides.",
    "G8_C15_DIS_LIGHTNG": "Grade 8 Chapter 15 (Natural Disasters). Lightning and thundering.",
    "G9_C1_MIC_ENV": "Grade 9 Chapter 1 (Applications of Micro-organisms). Micro-organisms, substrates, and environments.",
    "G9_C1_MIC_EFFECTS": "Grade 9 Chapter 1 (Applications of Micro-organisms). Effects and applications of micro-organisms.",
    "G9_C2_SEN_EYE": "Grade 9 Chapter 2 (Eye and Ear). Structure and defects of the human eye.",
    "G9_C2_SEN_EAR": "Grade 9 Chapter 2 (Eye and Ear). Structure and defects of the human ear.",
    "G9_C3_MAT_ELEMENTS": "Grade 9 Chapter 3 (Nature and Properties of Matter). Elements, compounds, and mixtures.",
    "G9_C3_MAT_MIXTURES": "Grade 9 Chapter 3 (Nature and Properties of Matter). Mixtures and separation ideas.",
    "G9_C4_FOR_FORCE": "Grade 9 Chapter 4 (Basic Concepts Associated with Force). Force, magnitude, direction, and point of application.",
    "G9_C4_FOR_GRAPH": "Grade 9 Chapter 4 (Basic Concepts Associated with Force). Graphical representation of force.",
    "G9_C5_PRE_PRESSURE": "Grade 9 Chapter 5 (Pressure Exerted by Solid). Pressure and factors affecting pressure.",
    "G9_C5_PRE_APPLY": "Grade 9 Chapter 5 (Pressure Exerted by Solid). Changing pressure factors as needed.",
    "G9_C6_CIR_HEART": "Grade 9 Chapter 6 (The Human Circulatory System). Structure of the heart; vessels.",
    "G9_C6_CIR_BLOOD": "Grade 9 Chapter 6 (The Human Circulatory System). Blood components and transfusion.",
    "G9_C7_PGS_INTRO": "Grade 9 Chapter 7 (Plant Growth Substances). Introduction to plant growth substances.",
    "G9_C7_PGS_ARTIF": "Grade 9 Chapter 7 (Plant Growth Substances). Uses of artificial growth substances.",
    "G9_C8_MOV_ANIMAL": "Grade 9 Chapter 8 (Support and Movements of Organisms). Bones, muscles, joints; animal movement.",
    "G9_C8_MOV_PLANT": "Grade 9 Chapter 8 (Support and Movements of Organisms). Support and movements of plants.",
    "G9_C9_EVO_ORIGIN": "Grade 9 Chapter 9 (The Evolutionary Process). Origin of Earth and life.",
    "G9_C9_EVO_BIODIV": "Grade 9 Chapter 9 (The Evolutionary Process). Evolution and importance for biodiversity.",
    "G9_C10_ELE_LYSIS": "Grade 9 Chapter 10 (Electrolysis). Electrolysis and solution changes by current.",
    "G9_C10_ELE_PLATE": "Grade 9 Chapter 10 (Electrolysis). Electroplating.",
    "G9_C11_DEN_INTRO": "Grade 9 Chapter 11 (Density). Introduction to density and units.",
    "G9_C11_DEN_HYDRO": "Grade 9 Chapter 11 (Density). Hydrometers.",
    "G9_C12_BIO_INTRO": "Grade 9 Chapter 12 (Bio-diversity). Bio-diversity and its importance.",
    "G9_C12_BIO_ECO": "Grade 9 Chapter 12 (Bio-diversity). Ecosystems, threats, and built vs natural environments.",
    "G9_C13_GRN_CONCEPT": "Grade 9 Chapter 13 (Artificial Environment and Green Concept). Artificial environment and green concept.",
    "G9_C13_GRN_AGRI": "Grade 9 Chapter 13 (Artificial Environment and Green Concept). Agricultural and industrial processes (green).",
    "G9_C14_WAV_REFLECT": "Grade 9 Chapter 14 (Reflection and Refraction of Waves). Reflection of light and sound.",
    "G9_C14_WAV_REFRACT": "Grade 9 Chapter 14 (Reflection and Refraction of Waves). Refraction of light.",
    "G9_C15_MAC_LEVER": "Grade 9 Chapter 15 (Simple Machines). Lever and inclined plane.",
    "G9_C15_MAC_PULLEY": "Grade 9 Chapter 15 (Simple Machines). Wheel and axle; pulleys.",
    "G9_C16_NANO_INTRO": "Grade 9 Chapter 16 (Nanotechnology and its Applications). Nanometer and nanotechnology basics.",
    "G9_C16_NANO_APPS": "Grade 9 Chapter 16 (Nanotechnology and its Applications). Applications and future of nanotechnology.",
    "G9_C17_LIG_OCCUR": "Grade 9 Chapter 17 (Lightning Accidents). How lightning occurs.",
    "G9_C17_LIG_PREVENT": "Grade 9 Chapter 17 (Lightning Accidents). Prevention of lightning accidents.",
    "G9_C18_DIS_TYPES": "Grade 9 Chapter 18 (Natural Disasters). Cyclones, earthquakes, tsunami, wild fires.",
    "G9_C18_DIS_WARMING": "Grade 9 Chapter 18 (Natural Disasters). Global warming and disasters.",
    "G9_C19_RES_WATER": "Grade 9 Chapter 19 (Sustainable Use of Natural Resources). Sustainable use of water.",
    "G9_C19_RES_MINERAL": "Grade 9 Chapter 19 (Sustainable Use of Natural Resources). Sustainable use of minerals, rocks, and trees."
}

FALLBACK_TOPIC_ID = "G6_C1_ORG_CHARS"

OLD_TO_NEW_TOPIC_ID: dict[str, str] = {
    # Best-effort migration from previous S-section IDs → chapter-aligned C IDs
    "G6_S1_ORG_CHARS": "G6_C1_ORG_CHARS",
    "G6_S1_ORG_CLASS": "G6_C1_ORG_DIFF",
    "G6_S2_MAT_STATES": "G6_C2_MAT_STATES",
    "G6_S2_MAT_PROPS": "G6_C2_MAT_PROPS",
    "G6_S4_ENE_SOURCES": "G6_C4_ENE_SOURCES",
    "G6_S8_ELE_CIRCUITS": "G6_C8_ELE_CIRCUITS",
    "G6_S8_ELE_CONDINS": "G6_C8_ELE_CONDINS",
    "G7_S1_PLA_DIVER": "G7_C1_PLA_DIVER",
    "G7_S1_PLA_CLASSIF": "G7_C1_PLA_CLASSIF",
    "G7_S2_STA_CHARGES": "G7_C2_STA_CHARGES",
    "G7_S2_STA_CAPACIT": "G7_C2_STA_CAPACIT",
    "G7_S3_ELE_SOURCES": "G7_C3_ELE_SOURCES",
    "G7_S3_ELE_CURRENTS": "G7_C3_ELE_CURRENTS",
    "G7_S4_WAT_SOLVENT": "G7_C4_WAT_SOLVENT",
    "G7_S4_WAT_COOLANT": "G7_C4_WAT_COOLANT",
    "G7_S5_ACI_IDENTIF": "G7_C5_ACI_IDENTIF",
    "G7_S5_ACI_INDICAT": "G7_C5_ACI_INDICAT",
    "G7_S6_ANI_CLASSIF": "G7_C6_ANI_CLASSIF",
    "G7_S6_ANI_ADAPTAT": "G7_C6_ANI_ADAPTAT",
    "G7_S7_ENE_FORMS": "G7_C7_ENE_FORMS",
    "G7_S7_ENE_TRANSF": "G7_C7_ENE_TRANSF",
    "G7_S8_EAR_STRUCT": "G7_C8_EAR_STRUCT",
    "G7_S8_EAR_TECTON": "G7_C8_EAR_TECTON",
    "G7_S9_LIG_SHADOWS": "G7_C9_LIG_SHADOWS",
    "G7_S9_LIG_MIRRORS": "G7_C9_LIG_MIRRORS",
    "G7_S10_MIC_LIGHT": "G7_C10_MIC_LIGHT",
    "G7_S10_MIC_ELECTR": "G7_C10_MIC_ELECTR",
    "G8_S1_BIO_DIVER": "G8_C1_MIC_INTRO",
    "G8_S1_BIO_CLASSIF": "G8_C2_ANI_VERT",
    "G8_S2_TIS_PLANT": "G8_C3_PLA_LEAVES",
    "G8_S2_TIS_ANIMAL": "G8_C9_HUM_NERVSKIN",
    "G8_S3_PHO_PROCESS": "G8_C11_PHO_PROCESS",
    "G8_S3_PHO_IMPORT": "G8_C11_PHO_TRANSP",
    "G8_S4_MAT_ELEMENTS": "G8_C4_MAT_PARTICLE",
    "G8_S4_MAT_COMPOUNDS": "G9_C3_MAT_ELEMENTS",
    "G8_S5_MAT_DENSITY": "G9_C11_DEN_INTRO",
    "G8_S5_MAT_THERMAL": "G8_C4_MAT_PROPS",
    "G8_S6_CHA_PHYSICAL": "G8_C8_CHA_PHYSCHEM",
    "G8_S6_CHA_BURNING": "G8_C8_CHA_COMBUST",
    "G8_S7_FOR_TYPES": "G9_C4_FOR_FORCE",
    "G8_S7_FOR_PRESSURE": "G9_C5_PRE_PRESSURE",
    "G8_S8_STA_PHENOM": "G7_C2_STA_CHARGES",
    "G8_S8_STA_LIGHTNG": "G8_C15_DIS_LIGHTNG",
    "G9_S1_SYS_DIGEST": "G7_C12_BIO_SYSTEMS",
    "G9_S1_SYS_CIRCUL": "G9_C6_CIR_HEART",
    "G9_S2_RHY_EARTH": "G8_C14_SOL_SYSTEM",
    "G9_S2_RHY_CLIMATE": "G6_C11_WEA_WEATHER",
    "G9_S3_LIG_REFRAC": "G9_C14_WAV_REFRACT",
    "G9_S3_LIG_LENSES": "G9_C14_WAV_REFRACT",
    "G9_S4_SOU_PROPAG": "G7_C11_SOU_PROPAG",
    "G9_S4_SOU_HEARING": "G9_C2_SEN_EAR",
    "G9_S5_HEA_EXPANS": "G7_C14_HEA_MEASURE",
    "G9_S5_HEA_TRANSF": "G7_C14_HEA_TRANSF",
    "G9_S6_NAT_ATOMS": "G9_C3_MAT_ELEMENTS",
    "G9_S6_NAT_CONFIG": "G9_C3_MAT_ELEMENTS",
    "G9_S7_ACI_SALTS": "G7_C5_ACI_IDENTIF",
    "G9_S7_ACI_NEUTRAL": "G7_C5_ACI_INDICAT",
}


def normalize_topic_id(topic_id: str) -> str:
    """Map legacy S-IDs to current C-IDs when possible."""
    tid = str(topic_id or "").strip()
    return OLD_TO_NEW_TOPIC_ID.get(tid, tid)


def chapters_covered() -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for tid, m in TOPIC_META.items():
        out.setdefault(int(m["grade"]), [])
        ch = int(m["chapter"])
        if ch not in out[int(m["grade"])]:
            out[int(m["grade"])].append(ch)
    for g in out:
        out[g] = sorted(out[g])
    return out
