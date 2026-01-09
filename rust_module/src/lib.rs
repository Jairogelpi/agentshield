use pyo3::prelude::*;
use pyo3::types::PyBytes;
// Imports Cleaned
use regex::Regex;
use lazy_static::lazy_static;
use std::io::Write;
use crc32fast::Hasher as Crc32;

// --- 1. RUST REGEX ENGINE (PII GUARD) ---
// Autómatas DFA pre-compilados. Velocidad O(n).
lazy_static! {
    static ref EMAIL_RE: Regex = Regex::new(r"(?i)\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b").unwrap();
    static ref PHONE_RE: Regex = Regex::new(r"\+(9[976]\d|8[987530]\d|6[987]\d|5[90]\d|42\d|3[875]\d|2[98654321]\d|9[8543210]|8[6421]|6[6543210]|5[87654321]|4[987654310]|3[9643210]|2[70]|7|1)\d{1,14}").unwrap();
    static ref IP_RE: Regex = Regex::new(r"\b(?:\d{1,3}\.){3}\d{1,3}\b").unwrap();
    static ref CC_RE: Regex = Regex::new(r"\b(?:\d{4}[- ]?){3}\d{4}\b").unwrap();
}

/// Escanea texto ultra-rápido buscando PII.
#[pyfunction]
pub fn scan_pii_fast(text: &str) -> Vec<String> {
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
pub fn scrub_pii_fast(text: &str) -> String {
    let mut clean = text.to_string();
    clean = EMAIL_RE.replace_all(&clean, "<EMAIL>").to_string();
    clean = PHONE_RE.replace_all(&clean, "<PHONE>").to_string();
    clean = IP_RE.replace_all(&clean, "<IP_ADDRESS>").to_string();
    clean = CC_RE.replace_all(&clean, "<CREDIT_CARD>").to_string();
    clean
}

// --- 2. ZERO-COPY IMAGE SIGNING (C2PA - Manual Binary Injection) ---
#[pyfunction]
pub fn sign_c2pa_image_fast(
    py: Python<'_>, 
    image_bytes: &[u8], 
    private_key_pem: &str, 
    manifest_json: &str
) -> PyResult<PyObject> {
// ... existing impl remains same ...
    // A. Firma Criptográfica
    // Use Fully Qualified syntax to avoid trait confusion
    use rsa::pkcs8::DecodePrivateKey;
    use rsa::{RsaPrivateKey, Pkcs1v15Sign};
    use sha2::{Sha256, Digest};
    use base64::{Engine as _, engine::general_purpose::STANDARD as BASE64};

    let private_key = RsaPrivateKey::from_pkcs8_pem(private_key_pem)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Invalid Key: {}", e)))?;

    let mut hasher = Sha256::new();
    hasher.update(manifest_json.as_bytes());
    let hashed = hasher.finalize();

    // Explicitly cast traits if needed, but standard usage should work.
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

    // B. Inyección de Metadatos (Manual Handling)
    let mut output_vec = Vec::with_capacity(image_bytes.len() + payload_bytes.len() + 100);

    if image_bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        // --- PROCESAR PNG (Inject tEXt chunk) ---
        // Header (8 bytes)
        output_vec.extend_from_slice(&image_bytes[0..8]);
        
        // Prepare tEXt chunk: Keyword + Null + Text
        let mut chunk_data = Vec::new();
        chunk_data.extend_from_slice(b"AgentShield-C2PA");
        chunk_data.push(0);
        chunk_data.extend_from_slice(payload_bytes);
        
        let length = chunk_data.len() as u32;
        let chunk_type = b"tEXt";
        
        // 1. Length (Big Endian)
        output_vec.extend_from_slice(&length.to_be_bytes());
        // 2. Type
        output_vec.extend_from_slice(chunk_type);
        // 3. Data
        output_vec.extend_from_slice(&chunk_data);
        // 4. CRC (Type + Data)
        let mut crc = Crc32::new();
        crc.update(chunk_type);
        crc.update(&chunk_data);
        output_vec.extend_from_slice(&crc.finalize().to_be_bytes());
        
        // Append rest of original image (starting after header)
        output_vec.extend_from_slice(&image_bytes[8..]);

    } else if image_bytes.starts_with(b"\xff\xd8") {
        // --- PROCESAR JPEG (Inject COM segment) ---
        // SOI (FF D8)
        output_vec.extend_from_slice(&image_bytes[0..2]);
        
        // COM Segment: FF FE <Length> <Data>
        // Length includes the 2 bytes of length itself.
        // Data length cannot exceed 65533 (65535 - 2).
        if payload_bytes.len() < 65500 {
            output_vec.push(0xFF);
            output_vec.push(0xFE);
            let length = (payload_bytes.len() + 2) as u16;
            output_vec.extend_from_slice(&length.to_be_bytes());
            output_vec.extend_from_slice(payload_bytes);
        }
        
        // Append rest of original image
        output_vec.extend_from_slice(&image_bytes[2..]);

    } else {
        // Fallback
        output_vec.extend_from_slice(image_bytes);
    }

    Ok(pyo3::types::PyBytes::new_bound(py, &output_vec).unbind().into())
}

/// El módulo Python
#[pymodule]
fn agentshield_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sign_c2pa_image_fast, m)?)?;
    m.add_function(wrap_pyfunction!(scan_pii_fast, m)?)?;
    m.add_function(wrap_pyfunction!(scrub_pii_fast, m)?)?;
    Ok(())
}
