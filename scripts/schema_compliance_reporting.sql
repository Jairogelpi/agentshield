-- Tabla de Marcos Legales (Templates)
CREATE TABLE IF NOT EXISTS regulatory_frameworks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL, -- e.g., "EU AI Act", "GDPR", "HIPAA"
    description TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Mapeo: Qué evento técnico satisface qué artículo legal
-- AHORA CON VECTORES (RAG)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS regulatory_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    framework_id UUID REFERENCES regulatory_frameworks(id),
    legal_article VARCHAR(50), -- e.g., "Art 32.1.b"
    legal_text TEXT, -- "Ability to ensure the ongoing confidentiality..."
    technical_event_type VARCHAR(100), -- "PII_BLOCK", "ENCRYPTION"
    evidence_query TEXT, -- SQL query hint or description
    embedding vector(1536), -- OpenAI Embedding
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Función de Búsqueda Semántica Legal
CREATE OR REPLACE FUNCTION match_legal_docs(
    query_embedding vector(1536),
    match_threshold float,
    match_count int,
    filter_framework text
)
RETURNS TABLE (
    id UUID,
    legal_article VARCHAR,
    legal_text TEXT,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        rm.id,
        rm.legal_article,
        rm.legal_text,
        1 - (rm.embedding <=> query_embedding) as similarity
    FROM regulatory_mappings rm
    JOIN regulatory_frameworks rf ON rm.framework_id = rf.id
    WHERE 1 - (rm.embedding <=> query_embedding) > match_threshold
    AND rf.name = filter_framework
    ORDER BY rm.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Insertamos datos semilla (Seed Data)
INSERT INTO regulatory_frameworks (name, description) VALUES 
('EU AI Act', 'Regulation laying down harmonised rules on artificial intelligence'), 
('GDPR', 'General Data Protection Regulation')
ON CONFLICT DO NOTHING;

-- Nota: Los embeddings reales se poblarían con un script de python 'embed_laws.py'
-- Aquí insertamos datos dummy para estructura, en prod se haría UPDATE con vectores reales.
DO $$
DECLARE
    gdpr_id UUID;
BEGIN
    SELECT id INTO gdpr_id FROM regulatory_frameworks WHERE name = 'GDPR' LIMIT 1;
    
    INSERT INTO regulatory_mappings (framework_id, legal_article, technical_event_type, legal_text)
    VALUES 
    (gdpr_id, 'Art 32', 'FILE_UPLOAD_BLOCKED', 'Taking into account the state of the art, the costs of implementation and the nature, scope, context and purposes of processing as well as the risk of varying likelihood and severity for the rights and freedoms of natural persons, the controller and the processor shall implement appropriate technical and organisational measures to ensure a level of security appropriate to the risk.')
    ON CONFLICT DO NOTHING;
END $$;
