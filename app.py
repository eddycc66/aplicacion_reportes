import os
from flask import Flask, request, send_file, jsonify, send_from_directory
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
import tempfile
import traceback

# ====== CONFIG ======
PG_DB = "samaipata_bd"
PG_USER = "postgres"
PG_PASS = "a1B6033242"
PG_HOST = "localhost"
PG_PORT = "5432"

GEOSERVER_WMS = "http://localhost:8080/geoserver/samaipata/wms"
WMS_LAYER_LOTES = "samaipata:lotes_limpios"

app = Flask(__name__, static_folder="static", template_folder=".")
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False

def pg_conn():
    try:
        conn = psycopg2.connect(
            dbname=PG_DB, 
            user=PG_USER, 
            password=PG_PASS, 
            host=PG_HOST, 
            port=PG_PORT
        )
        return conn
    except Exception as e:
        print(f"❌ Error conectando a PostgreSQL: {e}")
        return None

# ---------- Rutas de front ----------
@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/static/<path:path>")
def send_static(path):
    return send_from_directory("static", path)

# ---------- API: Info por id_predio (datos_distrito) ----------
@app.route("/info_predio")
def info_predio():
    conn = None
    try:
        id_predio = request.args.get("id_predio")
        print(f"📋 Consultando predio: {id_predio}")
        
        if not id_predio:
            return jsonify({"error": "Falta id_predio"}), 400

        conn = pg_conn()
        if not conn:
            return jsonify({"error": "Error de conexión a la base de datos"}), 500
            
        # Primero intentamos con datos_distrito
        sql = """
            SELECT 
                d.codigo,
                d.nombre_y_apellidos,
                d.carnet,
                d.tipo_inmueble,
                d.supconstruccion_m2,
                d.uso_de_edificacion,
                d.tipologia_const,
                d.id_predio,
                l."MANZANO" as manzano,  -- CORREGIDO: l.manzano -> l."MANZANO"
                l."LOTE" as lote,        -- CORREGIDO: l.lote -> l."LOTE"
                l.uso_suelo,
                l.propietari
            FROM datos_distrito d
            LEFT JOIN lotes_limpios l ON l.id_predio = d.id_predio
            WHERE d.id_predio = %s
            LIMIT 1;
        """
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (id_predio,))
            row = cur.fetchone()

        if row:
            print(f"✅ Predio encontrado en datos_distrito: {id_predio}")
            return jsonify(row)
            
        # Si no está en datos_distrito, buscamos en lotes_limpios
        sql = """
            SELECT 
                id_predio,
                "MANZANO" as manzano,    -- CORREGIDO: manzano -> "MANZANO"
                "LOTE" as lote,          -- CORREGIDO: lote -> "LOTE"
                uso_suelo,
                propietari,
                NULL as codigo,
                NULL as nombre_y_apellidos,
                NULL as carnet,
                NULL as tipo_inmueble,
                NULL as supconstruccion_m2,
                NULL as uso_de_edificacion,
                NULL as tipologia_const
            FROM lotes_limpios
            WHERE id_predio = %s
            LIMIT 1;
        """
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (id_predio,))
            row = cur.fetchone()

        if row:
            print(f"✅ Predio encontrado en lotes_limpios: {id_predio}")
            return jsonify(row)

        print(f"❌ Predio no encontrado: {id_predio}")
        return jsonify({"error": "Predio no encontrado"}), 404
        
    except Exception as e:
        print(f"❌ Error en info_predio: {e}")
        traceback.print_exc()
        return jsonify({"error": f"Error interno del servidor: {str(e)}"}), 500
    finally:
        if conn:
            conn.close()

# ---------- API: Estadísticas para dashboard ----------
@app.route("/estadisticas/uso_suelo")
def estadisticas_uso_suelo():
    conn = None
    try:
        conn = pg_conn()
        if not conn:
            return jsonify([{"uso_suelo": "Error de conexión", "cantidad": 0}])
            
        sql = """
            SELECT COALESCE(uso_suelo,'SIN CLASE') AS uso_suelo, COUNT(*) AS cantidad
            FROM lotes_limpios
            GROUP BY 1
            ORDER BY 2 DESC;
        """
        
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            data = cur.fetchall()
            
        return jsonify(data)
        
    except Exception as e:
        print(f"❌ Error en estadísticas: {e}")
        traceback.print_exc()
        return jsonify([{"uso_suelo": "Error", "cantidad": 0}])
    finally:
        if conn:
            conn.close()

# ---------- API: Proxy de GetFeatureInfo (evita CORS) ----------
@app.route("/gfi")
def gfi():
    try:
        required = ["bbox", "width", "height", "x", "y"]
        for k in required:
            if k not in request.args:
                return jsonify({"error": f"Falta parámetro {k}"}), 400

        params = {
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetFeatureInfo",
            "layers": WMS_LAYER_LOTES,
            "query_layers": WMS_LAYER_LOTES,
            "info_format": "application/json",
            "srs": "EPSG:32720",
            "bbox": request.args["bbox"],
            "width": request.args["width"],
            "height": request.args["height"],
            "x": request.args["x"],
            "y": request.args["y"],
        }
        
        print(f"🌐 Consultando GeoServer: {params}")
        r = requests.get(GEOSERVER_WMS, params=params, timeout=30)
        
        if r.status_code != 200:
            print(f"❌ GeoServer respondió con error: {r.status_code}")
            return jsonify({"error": f"GeoServer error: {r.status_code}"}), r.status_code
            
        return (r.content, r.status_code, {"Content-Type": r.headers.get("Content-Type", "application/json")})
        
    except Exception as e:
        print(f"❌ Error en GFI: {e}")
        traceback.print_exc()
        return jsonify({"error": "Error al conectar con GeoServer"}), 500

# ---------- Auxiliares para reporte ----------
def get_datos_para_reporte(id_predio):
    conn = None
    try:
        conn = pg_conn()
        if not conn:
            return None
            
        sql = """
            SELECT 
                COALESCE(d.id_predio, l.id_predio) as id_predio,
                l."MANZANO" as manzano,  -- CORREGIDO: l.manzano -> l."MANZANO"
                l."LOTE" as lote,        -- CORREGIDO: l.lote -> l."LOTE"
                l.propietari,
                l.uso_suelo,
                d.codigo,
                d.nombre_y_apellidos,
                d.carnet,
                d.tipo_inmueble,
                d.supconstruccion_m2,
                d.uso_de_edificacion,
                d.tipologia_const
            FROM lotes_limpios l
            LEFT JOIN datos_distrito d ON d.id_predio = l.id_predio
            WHERE l.id_predio = %s
            LIMIT 1;
        """
        
        with conn.cursor() as cur:
            cur.execute(sql, (id_predio,))
            row = cur.fetchone()
            
        return row
        
    except Exception as e:
        print(f"❌ Error obteniendo datos para reporte: {e}")
        traceback.print_exc()
        return None
    finally:
        if conn:
            conn.close()

def get_bbox_lote(id_predio):
    conn = None
    try:
        conn = pg_conn()
        if not conn:
            return None
            
        sql = """
            SELECT 
                ST_XMin(geom) AS minx, 
                ST_YMin(geom) AS miny,
                ST_XMax(geom) AS maxx, 
                ST_YMax(geom) AS maxy
            FROM lotes_limpios
            WHERE id_predio = %s;
        """
        
        with conn.cursor() as cur:
            cur.execute(sql, (id_predio,))
            row = cur.fetchone()
            
        return row
        
    except Exception as e:
        print(f"❌ Error obteniendo bbox: {e}")
        traceback.print_exc()
        return None
    finally:
        if conn:
            conn.close()

def descargar_png_mapa(bbox, ancho=600, alto=400):
    if not bbox:
        return None
    
    try:
        # Ajustar la bbox para agregar un pequeño margen
        minx, miny, maxx, maxy = bbox
        dx = (maxx - minx) * 0.1  # 10% de margen
        dy = (maxy - miny) * 0.1  # 10% de margen
        
        bbox_con_margen = (minx - dx, miny - dy, maxx + dx, maxy + dy)
        
        params = {
            "service": "WMS",
            "version": "1.1.1",
            "request": "GetMap",
            "layers": WMS_LAYER_LOTES,
            "styles": "",
            "bbox": ",".join(map(str, bbox_con_margen)),
            "srs": "EPSG:32720",
            "width": str(ancho),
            "height": str(alto),
            "format": "image/png",
            "transparent": "false",
        }
        
        r = requests.get(GEOSERVER_WMS, params=params, timeout=30)
        if r.status_code == 200:
            # Crear un archivo temporal
            fd, img_path = tempfile.mkstemp(suffix='.png')
            with os.fdopen(fd, 'wb') as f:
                f.write(r.content)
            return img_path
            
        return None
        
    except Exception as e:
        print(f"❌ Error descargando mapa: {e}")
        traceback.print_exc()
        return None

# ---------- API: Reporte PDF ----------
@app.route("/reporte")
def reporte():
    try:
        id_predio = request.args.get("id_predio")
        if not id_predio:
            return "Falta id_predio", 400

        datos = get_datos_para_reporte(id_predio)
        if not datos:
            return f"No se encontró el predio {id_predio}", 404

        # Campos ordenados para tabla
        labels = [
            "ID Predio", "Manzano", "Lote", "Propietario (lotes)", "Uso de Suelo",
            "Código", "Nombre y Apellidos", "CI", "Tipo de Inmueble", "Sup. Construcción (m²)",
            "Uso de Edificación", "Tipología Constructiva"
        ]

        # Descargar mini-mapa del lote
        bbox = get_bbox_lote(id_predio)
        img_map = descargar_png_mapa(bbox) if bbox else None

        # Generar PDF
        pdf_path = f"reporte_{id_predio}.pdf"
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph(f"Reporte del Predio {id_predio}", styles["Title"]))
        story.append(Spacer(1, 10))

        if img_map and os.path.exists(img_map):
            story.append(Paragraph("Ubicación del Predio", styles["Heading3"]))
            story.append(Image(img_map, width=400, height=300))
            story.append(Spacer(1, 10))

        # Tabla de atributos
        data = [[Paragraph("<b>Atributo</b>", styles["Normal"]),
                 Paragraph("<b>Valor</b>", styles["Normal"])]]
        
        for i, label in enumerate(labels):
            value = datos[i] if i < len(datos) else "N/D"
            txt = "" if value is None else str(value)
            data.append([label, txt])

        table = Table(data, colWidths=[200, 250])
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(table)

        doc = SimpleDocTemplate(pdf_path, pagesize=A4, 
                               leftMargin=36, rightMargin=36, 
                               topMargin=36, bottomMargin=36)
        doc.build(story)

        # Limpieza imagen temporal
        if img_map and os.path.exists(img_map):
            try:
                os.remove(img_map)
            except Exception:
                pass

        return send_file(pdf_path, as_attachment=True)
        
    except Exception as e:
        print(f"❌ Error generando reporte: {e}")
        traceback.print_exc()
        return f"Error al generar el reporte: {str(e)}", 500

# Ruta de salud para verificar que el servidor funciona
@app.route("/health")
def health():
    return jsonify({"status": "ok", "message": "Servidor funcionando correctamente"})

if __name__ == "__main__":
    print("🚀 Iniciando servidor Flask...")
    print("📍 Endpoints disponibles:")
    print("   - http://localhost:5000/ (Interfaz principal)")
    print("   - http://localhost:5000/health (Verificar salud del servidor)")
    print("   - http://localhost:5000/info_predio?id_predio=XXX (Consultar predio)")
    print("   - http://localhost:5000/estadisticas/uso_suelo (Estadísticas)")
    print("   - http://localhost:5000/reporte?id_predio=XXX (Generar reporte)")
    
    # Ejecuta en http://localhost:5000
    app.run(debug=True, host="0.0.0.0", port=5000)