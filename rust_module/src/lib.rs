// agentshield_core/rust_module/src/lib.rs
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use rsa::{RsaPrivateKey, Pkcs1v15Sign};
use rsa::pkcs8::DecodePrivateKey;
use sha2::{Sha256, Digest};
use base64::{Engine as _, engine::general_purpose::STANDARD as BASE64};
use std::io::Cursor;
use img_parts::png::{Png, Chunk};
use img_parts::jpeg::Jpeg;
use img_parts::ImageEXIF;
use regex::Regex;
use lazy_static::lazy_static;

// --- 1. RUST REGEX ENGINE (PII GUARD) ---
// Autómatas DFA pre-compilados. Velocidad O(n).
lazy_static! {
    static ref EMAIL_RE: Regex = Regex::new(r"(?i)\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b").unwrap();
    static ref PHONE_RE: Regex = Regex::new(r"\+(9[976]\d|8[987530]\d|6[987]\d|5[90]\d|42\d|3[875]\d|2[98654321]\d|9[8543210]|8[6421]|6[6543210]|5[87654321]|4[987654310]|3[9643210]|2[70]|7|1)\d{1,14}").unwrap();
    static ref IP_RE: Regex = Regex::new(r"\b(?:\d{1,3}\.){3}\d{1,3}\b").unwrap();
    static ref CC_RE: Regex = Regex::new(r"\b(?:\d{4}[- ]?){3}\d{4}\b").unwrap();
}

/// Escanea texto ultra-rápido buscando PII.
/// Devuelve una lista de las categorías detectadas para que Python haga el reemplazo si es necesario.
/// (O podríamos reemplazar aquí mismo para máxima velocidad, pero dejemos que Python orquesre).
#[pyfunction]
fn scan_pii_fast(text: &str) -> Vec<String> {
    let mut findings = Vec::with_capacity(4);
    
    // Check de bajo nivel sin allocar memoria extra
    if EMAIL_RE.is_match(text) { findings.push("EMAIL".to_string()); }
    if PHONE_RE.is_match(text) { findings.push("PHONE".to_string()); }
    if IP_RE.is_match(text) { findings.push("IP_ADDRESS".to_string()); }
    if CC_RE.is_match(text) { findings.push("CREDIT_CARD".to_string()); }
    
    findings
}

/// Función de reemplazo rápido (Opción B: Scrubbing directo en Rust)
#[pyfunction]
fn scrub_pii_fast(text: &str) -> String {
    let mut clean = text.to_string();
    clean = EMAIL_RE.replace_all(&clean, "<EMAIL>").to_string();
    clean = PHONE_RE.replace_all(&clean, "<PHONE>").to_string();
    clean = IP_RE.replace_all(&clean, "<IP_ADDRESS>").to_string();
    clean = CC_RE.replace_all(&clean, "<CREDIT_CARD>").to_string();
    clean
}

// --- 2. ZERO-COPY IMAGE SIGNING (C2PA) ---
#[pyfunction]
fn sign_c2pa_image_fast(
    py: Python, 
    image_bytes: &[u8], 
    private_key_pem: &str, 
    manifest_json: &str
) -> PyResult<PyObject> {

    // A. Firma Criptográfica
    let private_key = RsaPrivateKey::from_pkcs8_pem(private_key_pem)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid Key: {}", e)))?;

    let mut hasher = Sha256::new();
    hasher.update(manifest_json.as_bytes());
    let hashed = hasher.finalize();

    let signature = private_key.sign(Pkcs1v15Sign::new::<Sha256>(), &hashed)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Signing failed: {}", e)))?;
    
    let signature_b64 = BASE64.encode(signature);

    let full_payload = serde_json::json!({
        "manifest": serde_json::from_str::<serde_json::Value>(manifest_json).unwrap_or_default(),
        "signature": signature_b64,
        "algo": "rsa-sha256-rust-zero-copy"
    });
    let payload_str = full_payload.to_string();
    let payload_bytes = payload_str.as_bytes();

    // B. Inyección de Metadatos (Sin recodificar píxeles)
    let output_vec: Vec<u8>;

    // Detectar cabecera mágica
    if image_bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        // --- PROCESAR PNG ---
        let mut png = Png::from_bytes(image_bytes.into())
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(format!("Invalid PNG: {}", e)))?;

        // Inyectamos un chunk 'tEXt' (Key-Value)
        // Key: "AgentShield-C2PA"
        // Value: JSON payload
        // Formato tEXt: Keyword + Null + Text
        let mut data = Vec::new();
        data.extend_from_slice(b"AgentShield-C2PA");
        data.push(0); // Separador Null
        data.extend_from_slice(payload_bytes);

        let chunk = Chunk::new(*b"tEXt", data);
        png.chunks_mut().push(chunk);

        let mut writer = Cursor::new(Vec::with_capacity(image_bytes.len() + 500));
        png.write_to(&mut writer)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(format!("Failed to write PNG: {}", e)))?;
        output_vec = writer.into_inner();

    } else if image_bytes.starts_with(b"\xff\xd8") {
        // --- PROCESAR JPEG ---
        let mut jpeg = Jpeg::from_bytes(image_bytes.into())
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(format!("Invalid JPEG: {}", e)))?;

        // Inyectar en segmento COM (Comment). Es seguro y común.
        // Ojo: Max 64KB en JPEG segments. Si el payload es muy grande, falla.
        // Asumimos payload < 64KB.
        if payload_bytes.len() > 60000 {
             return Err(pyo3::exceptions::PyValueError::new_err("Payload too large for JPEG COM segment"));
        }
        
        jpeg.set_comment(Some(payload_str.clone())); 
        // Alternativamente, se podría usar set_exif si tuvieramos el blob EXIF binario completo.
        
        let mut writer = Cursor::new(Vec::with_capacity(image_bytes.len() + 500));
        jpeg.write_to(&mut writer)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(format!("Failed to write JPEG: {}", e)))?;
        output_vec = writer.into_inner();

    } else {
        // Fallback: Retornar original si no es soportado (O re-codificar si quisiéramos)
        // Para este ejemplo "God Tier", solo soportamos PNG/JPEG con zero-copy.
        // Si no es soportado, devolvemos bytes originales para no romper el flujo.
        return Ok(PyBytes::new(py, image_bytes).into());
    }

    Ok(PyBytes::new(py, &output_vec).into())
}

/// El módulo Python
#[pymodule]
fn agentshield_rust(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sign_c2pa_image_fast, m)?)?;
    m.add_function(wrap_pyfunction!(scan_pii_fast, m)?)?;
    m.add_function(wrap_pyfunction!(scrub_pii_fast, m)?)?;
    Ok(())
}
