import json
import os
import re
import pandas as pd

# Define paths
INPUT_FILE = "/home/Carlo/Code/Natural Language Processing/data/anamnesiterapie.txt"
OUTPUT_JSON = "/home/Carlo/Code/Natural Language Processing/data/anamnesiterapie_structured.json"
OUTPUT_CSV = "/home/Carlo/Code/Natural Language Processing/data/anamnesiterapie_structured.csv"

def clean_text(text):
    if not text:
        return ""
    # Remove multiple spaces, newlines, and trailing/leading spaces
    return re.sub(r'\s+', ' ', text).strip()

def clean_drug_name(name):
    if not name:
        return ""
    name = name.lower()
    suffixes = [
        " sandoz", " sand", " teva", " doc", " abc", " auro", " eg", " my", " zen", 
        " sa", " au", " l.f.m.", " mylan", " generic", " generico", " ratiopharm",
        " chrono", " retard", " division", " divisibile", " divisibili", " rp", " pr"
    ]
    for suffix in suffixes:
        name = name.replace(suffix, "")
    # Remove punctuation
    name = re.sub(r'[\/\\,\-\:\(\)]', ' ', name)
    # Remove common dosage unit names to keep just the name tokens
    tokens = [t for t in name.split() if t not in ["cpr", "cps", "mg", "gtt", "ml", "mcg", "ui", "soluz", "iniett", "os", "fino", "a", "da", "per"]]
    return " ".join(tokens)

def parse_terapia_ingresso(text):
    if not text or text.strip().lower() in ["nessuna terapia domiciliare.", "nessuna"]:
        return []
    parts = text.split(";")
    drugs = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, details = part.split(":", 1)
            name = name.strip()
            details = details.strip()
        else:
            name = part
            details = ""
        drugs.append({
            "nome": name,
            "dettagli": details,
            "nome_pulito": clean_drug_name(name)
        })
    return drugs

def parse_terapia_dimissione(text):
    if not text or text.strip().lower() in ["nessuna terapia alla dimissione.", "nessuna"]:
        return []
    matches = re.findall(r'"([^"]+)"', text)
    if not matches:
        if ";" in text:
            matches = [p.strip() for p in text.split(";") if p.strip()]
        else:
            matches = [text.strip()]
            
    drugs = []
    for match in matches:
        match = match.strip()
        if not match:
            continue
        name_part = match
        instructions = ""
        if ":" in match:
            name_part, instructions = match.split(":", 1)
            name_part = name_part.strip()
            instructions = instructions.strip()
            
        brand_match = re.search(r'\(([^)]+)\)', name_part)
        brand = ""
        active_ingredient = name_part
        if brand_match:
            extracted_brand = brand_match.group(1).strip()
            if extracted_brand != "-":
                brand = extracted_brand
                active_ingredient = name_part.replace(f"({brand})", "").strip()
            else:
                active_ingredient = name_part.replace("(-)", "").strip()
            
        drugs.append({
            "nome_completo": name_part,
            "principio_attivo": active_ingredient,
            "commerciale_dettagli": brand,
            "istruzioni": instructions,
            "brand_pulito": clean_drug_name(brand if brand else active_ingredient),
            "principio_pulito": clean_drug_name(active_ingredient)
        })
    return drugs

def match_drugs(ingresso_list, dimissione_list):
    mantenuti = []
    sospesi = []
    aggiunti = []
    
    matched_dimissione_indices = set()
    meaningless_tokens = {"acido", "sodio", "potassio", "calcio", "magnesio", "ferro"}
    
    for ing in ingresso_list:
        ing_clean = ing["nome_pulito"]
        ing_tokens = set(ing_clean.split())
        ing_tokens_filtered = ing_tokens - meaningless_tokens
        
        found_match = False
        for idx, dim in enumerate(dimissione_list):
            dim_brand_clean = dim["brand_pulito"]
            dim_princ_clean = dim["principio_pulito"]
            
            dim_brand_tokens = set(dim_brand_clean.split())
            dim_princ_tokens = set(dim_princ_clean.split())
            
            overlap_brand = ing_tokens_filtered.intersection(dim_brand_tokens - meaningless_tokens)
            overlap_princ = ing_tokens_filtered.intersection(dim_princ_tokens - meaningless_tokens)
            
            substring_match = False
            if ing_clean:
                in_brand = (dim_brand_clean and ing_clean in dim_brand_clean) or (dim_brand_clean and dim_brand_clean in ing_clean)
                in_princ = (dim_princ_clean and ing_clean in dim_princ_clean)
                if in_brand or in_princ:
                    if ing_clean not in meaningless_tokens:
                        substring_match = True
            
            if overlap_brand or overlap_princ or substring_match:
                mantenuti.append({
                    "ingresso": ing["nome"],
                    "dimissione": dim["nome_completo"]
                })
                matched_dimissione_indices.add(idx)
                found_match = True
                break
                
        if not found_match:
            sospesi.append(ing["nome"])
            
    for idx, dim in enumerate(dimissione_list):
        if idx not in matched_dimissione_indices:
            aggiunti.append(dim["nome_completo"])
            
    return mantenuti, sospesi, aggiunti

def extract_comorbidities(text):
    text_lower = text.lower()
    comorbilita = {
        "ipertensione": int(any(x in text_lower for x in ["ipertensione", "iperteso", "ipertesa", "pressione alta"])),
        "diabete": int(any(x in text_lower for x in ["diabete", "diabetico", "diabetica"])),
        "dislipidemia": int(any(x in text_lower for x in ["dislipidemia", "ipercolesterolemia", "ipertrigliceridemia", "colesterolo"])),
        "obesita": int(any(x in text_lower for x in ["obesità", "obeso", "obesa", "sovrappeso"])),
        "fibrillazione_atriale": int(any(x in text_lower for x in ["fibrillazione atriale", " fa ", " fa,", " fa.", "cardiopalmo"])),
        "cardiopatia_ischemica": int(any(x in text_lower for x in ["ischemia", "ischemica", "infarto", "stemi", "nstemi", "angina", "stent", "angioplastica", "coronaropatia"])),
        "scompenso_cardiaco": int(any(x in text_lower for x in ["scompenso", "scompenso cardiaco"])),
        "insufficienza_renale": int(any(x in text_lower for x in ["insufficienza renale", "nefropatia", "creatinina"])),
        "distiroidismo": int(any(x in text_lower for x in ["tiroidite", "ipotiroidismo", "ipertiroidismo", "eutiroideo", "distiroidismo", "gozzo"])),
        "fumo": int(any(x in text_lower for x in ["fumatore", "fumatrice", "fumo", "fumato", "pack/year"]))
    }
    return comorbilita

def main():
    print("Loading data...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
        
    structured_data = []
    
    print("Preprocessing patients...")
    for item in raw_data:
        enc_id = item.get("encOid")
        referti = item.get("referti", [])
        
        anamnesi_raw = ""
        ingresso_raw = ""
        dimissione_raw = ""
        
        for ref in referti:
            tipo = ref.get("tipo")
            text = ref.get("testo", "")
            if tipo == "Anamnesi":
                anamnesi_raw = clean_text(text)
            elif tipo == "Terapia medica all'ingresso":
                ingresso_raw = clean_text(text)
            elif tipo == "Terapia alla Dimissione":
                dimissione_raw = clean_text(text)
                
        # Parse therapies
        ingresso_parsed = parse_terapia_ingresso(ingresso_raw)
        dimissione_parsed = parse_terapia_dimissione(dimissione_raw)
        
        # Reconcile medications
        mantenuti, sospesi, aggiunti = match_drugs(ingresso_parsed, dimissione_parsed)
        
        # Extract clinical features from anamnesi
        comorbilita = extract_comorbidities(anamnesi_raw)
        
        patient_record = {
            "encOid": enc_id,
            "anamnesi_testo": anamnesi_raw,
            "terapia_ingresso_testo": ingresso_raw,
            "terapia_dimissione_testo": dimissione_raw,
            "terapia_ingresso_farmaci": [{k: v for k, v in d.items() if k != "nome_pulito"} for d in ingresso_parsed],
            "terapia_dimissione_farmaci": [{k: v for k, v in d.items() if k not in ["brand_pulito", "principio_pulito"]} for d in dimissione_parsed],
            "farmaci_mantenuti": mantenuti,
            "farmaci_sospesi": sospesi,
            "farmaci_aggiunti": aggiunti,
            **comorbilita
        }
        structured_data.append(patient_record)
        
    print(f"Saving structured JSON to {OUTPUT_JSON}...")
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(structured_data, f, indent=2, ensure_ascii=False)
        
    print("Creating flat DataFrame for CSV output...")
    # For CSV, we can serialize list columns as JSON strings or string-joined representations
    csv_records = []
    for rec in structured_data:
        csv_rec = rec.copy()
        # stringify lists/dicts
        csv_rec["terapia_ingresso_farmaci"] = "|".join([d["nome"] for d in rec["terapia_ingresso_farmaci"]])
        csv_rec["terapia_dimissione_farmaci"] = "|".join([d["nome_completo"] for d in rec["terapia_dimissione_farmaci"]])
        csv_rec["farmaci_mantenuti"] = "|".join([f"{d['ingresso']}->{d['dimissione']}" for d in rec["farmaci_mantenuti"]])
        csv_rec["farmaci_sospesi"] = "|".join(rec["farmaci_sospesi"])
        csv_rec["farmaci_aggiunti"] = "|".join(rec["farmaci_aggiunti"])
        csv_records.append(csv_rec)
        
    df = pd.DataFrame(csv_records)
    print(f"Saving structured CSV to {OUTPUT_CSV}...")
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    print("Preprocessing completed successfully!")

if __name__ == "__main__":
    main()
