use pyo3::prelude::*;
use pyo3::types::PyBytes;
use rsa::{RsaPrivateKey, Pkcs1v15Sign};
use rsa::pkcs8::DecodePrivateKey;
use sha2::{Sha256, Digest};
use base64::{Engine as _, engine::general_purpose::STANDARD as BASE64};
use regex::Regex;
use lazy_static::lazy_static;
use std::io::Write;
use crc32fast::Hasher as Crc32;

// ... (Regex stuff remains same)

// --- 2. ZERO-COPY IMAGE SIGNING (C2PA - Manual Binary Injection) ---
#[pyfunction]
fn sign_c2pa_image_fast(
    py: Python<'_>, 
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

    Ok(PyBytes::new(py, &output_vec).unbind().into())
}

/// El módulo Python
/// El módulo Python
#[pymodule]
fn agentshield_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sign_c2pa_image_fast, m)?)?;
    m.add_function(wrap_pyfunction!(scan_pii_fast, m)?)?;
    m.add_function(wrap_pyfunction!(scrub_pii_fast, m)?)?;
    Ok(())
}
