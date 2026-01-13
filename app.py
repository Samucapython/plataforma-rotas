import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from math import radians, cos, sin, asin, sqrt
import requests
from streamlit_autorefresh import st_autorefresh

# 1. CONFIGURAÇÕES E ESTADO
st.set_page_config(page_title="Samuel Rota Pro", layout="wide")

if 'logado' not in st.session_state: st.session_state['logado'] = False
if 'df_otimizado' not in st.session_state: st.session_state['df_otimizado'] = None
if 'entregas_feitas' not in st.session_state: st.session_state['entregas_feitas'] = set()
if 'ver_mapa' not in st.session_state: st.session_state['ver_mapa'] = False

# Função para calcular distância real (para baixa automática)
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 # metros
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi/2)**2 + cos(phi1)*cos(phi2)*sin(dlambda/2)**2
    return 2 * R * asin(sqrt(a))

# Função para a linha grudar na rua (OSRM)
def obter_rota_ruas(coords_list):
    try:
        locs = ";".join([f"{lon},{lat}" for lat, lon in coords_list])
        url = f"http://router.project-osrm.org/route/v1/driving/{locs}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return [[p[1], p[0]] for p in r.json()['routes'][0]['geometry']['coordinates']]
    except: pass
    return coords_list

# 2. LOGIN
if not st.session_state['logado']:
    st.title("🔐 Acesso Samuel")
    with st.form("login"):
        u = st.text_input("Usuário")
        s = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            if u in ["ADMIN", "11972295576"]:
                st.session_state['logado'] = True
                st.rerun()
    st.stop()

# 3. GPS E AUTO-BAIXA
loc = get_geolocation()
if loc and 'coords' in loc:
    lat_vtr, lon_vtr = loc['coords']['latitude'], loc['coords']['longitude']
    
    # LÓGICA DE BAIXA AUTOMÁTICA (IGUAL AO ORIGINAL)
    if st.session_state['df_otimizado'] is not None:
        df_res = st.session_state['df_otimizado']
        for i, row in enumerate(df_res.itertuples()):
            if i not in st.session_state['entregas_feitas']:
                dist = haversine(lat_vtr, lon_vtr, row.Latitude, row.Longitude)
                if dist < 30: # Se estiver a menos de 30 metros, finaliza
                    st.session_state['entregas_feitas'].add(i)
                    st.toast(f"Parada {i+1} finalizada automaticamente!")
                    st.rerun()
else:
    st.warning("📍 Localizando motorista...")
    st.stop()

# 4. PROCESSAMENTO
if st.session_state['df_otimizado'] is None:
    arquivo = st.file_uploader("Subir Planilha", type=['csv', 'xlsx'])
    if arquivo and st.button("OTIMIZAR ROTA"):
        df_raw = pd.read_csv(arquivo) if arquivo.name.endswith('.csv') else pd.read_excel(arquivo)
        df = df_raw.groupby(['Latitude', 'Longitude'], as_index=False).agg({
            'AT ID': 'first', 'Sequence': 'first', 'SPX TN': 'first',
            'Destination Address': 'first', 'Bairro': 'first', 'City': 'first', 'Stop': 'count'
        })
        
        # Algoritmo de Otimização
        coords = [[lat_vtr, lon_vtr]] + df[['Latitude', 'Longitude']].values.tolist()
        manager = pywrapcp.RoutingIndexManager(len(coords), 1, 0)
        routing = pywrapcp.RoutingModel(manager)
        def d_c(f, t):
            p1, p2 = coords[manager.IndexToNode(f)], coords[manager.IndexToNode(t)]
            return int(haversine(p1[0], p1[1], p2[0], p2[1]))
        routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(d_c))
        sol = routing.SolveWithParameters(pywrapcp.DefaultRoutingSearchParameters())
        
        if sol:
            idx, ordem = routing.Start(0), []
            while not routing.IsEnd(idx):
                ordem.append(manager.IndexToNode(idx))
                idx = sol.Value(routing.NextVar(idx))
            st.session_state['df_otimizado'] = df.iloc[[i-1 for i in ordem if i > 0]].copy()
            st.rerun()

# 5. INTERFACE DE OPERAÇÃO
if st.session_state['df_otimizado'] is not None:
    st_autorefresh(interval=20000, key="nav_refresh") # Atualiza GPS a cada 20s
    df_res = st.session_state['df_otimizado']
    
    # Encontra a parada atual
    proxima_idx = next((i for i in range(len(df_res)) if i not in st.session_state['entregas_feitas']), None)

    if not st.session_state['ver_mapa']:
        # --- TELA DE LISTA ---
        if st.button("🗺️ VER MAPA COMPLETO", use_container_width=True, type="primary"):
            st.session_state['ver_mapa'] = True
            st.rerun()

        if proxima_idx is not None:
            dados = df_res.iloc[proxima_idx]
            st.markdown(f"### 📍 Próxima Parada: {proxima_idx + 1}")
            
            # Card Estilo Profissional
            c1, c2 = st.columns(2)
            with c1:
                st.write(f"**AT:** {dados['AT ID']}")
                st.write(f"**PEDIDO:** {dados['Sequence']}")
            with c2:
                st.write(f"**BR:** {dados['SPX TN']}")
                st.write(f"**VOLUMES:** {dados['Stop']}")
            
            st.info(f"🏠 **ENDEREÇO:**\n{dados['Destination Address']}")
            
            g_maps = f"https://www.google.com/maps/dir/?api=1&origin={lat_vtr},{lon_vtr}&destination={dados.Latitude},{dados.Longitude}&travelmode=driving"
            st.link_button("🚀 INICIAR NAVEGAÇÃO", g_maps, use_container_width=True)
            
            if st.button("⚠️ Pular para Próxima (Manual)"):
                st.session_state['entregas_feitas'].add(proxima_idx)
                st.rerun()
    else:
        # --- TELA DE MAPA (ESTILO ORIGINAL) ---
        if st.button("📋 VOLTAR PARA LISTA", use_container_width=True):
            st.session_state['ver_mapa'] = False
            st.rerun()

        # Mapa com Rotação e Linha OSRM
        m = folium.Map(location=[lat_vtr, lon_vtr], zoom_start=17, tilt=45) # Tilt simula visão 3D/Giro
        
        pts = [[lat_vtr, lon_vtr]] + df_res[['Latitude', 'Longitude']].values.tolist()
        rota_ruas = obter_rota_ruas(pts)
        
        # Linha que gruda na rua
        folium.PolyLine(rota_ruas, color="#2196F3", weight=5, opacity=0.8).add_to(m)
        
        # Motorista (Ponto Vermelho)
        folium.CircleMarker([lat_vtr, lon_vtr], radius=6, color="red", fill=True, popup="Você").add_to(m)

        for i, row in enumerate(df_res.itertuples()):
            cor = "#28a745" if i in st.session_state['entregas_feitas'] else "#212529"
            icone = folium.DivIcon(html=f'<div style="background-color:{cor}; color:white; border-radius:50%; width:22px; height:22px; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:bold; border:2px solid white;">{i+1}</div>')
            folium.Marker([row.Latitude, row.Longitude], icon=icone).add_to(m)

        st_folium(m, width="100%", height=600, key="mapa_samuel")
