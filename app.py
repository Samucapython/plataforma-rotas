import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from math import radians, cos, sin, asin, sqrt
import requests
from streamlit_autorefresh import st_autorefresh

# 1. ESTADO DE MEMÓRIA (O coração da mudança)
if 'logado' not in st.session_state: st.session_state['logado'] = False
if 'df_otimizado' not in st.session_state: st.session_state['df_otimizado'] = None
if 'entregas_feitas' not in st.session_state: st.session_state['entregas_feitas'] = set()
if 'ver_mapa' not in st.session_state: st.session_state['ver_mapa'] = False # Controla a troca de tela

def obter_rota_ruas(coords_list):
    try:
        locs = ";".join([f"{lon},{lat}" for lat, lon in coords_list])
        url = f"http://router.project-osrm.org/route/v1/driving/{locs}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=10)
        return [[p[1], p[0]] for p in r.json()['routes'][0]['geometry']['coordinates']]
    except: return coords_list

# Layout da página
st.set_page_config(page_title="Samuel Rota", layout="wide")

# Login
if not st.session_state['logado']:
    st.title("🔐 Login")
    with st.form("login"):
        user = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            if user == "ADMIN" or user == "11972295576":
                st.session_state['logado'] = True
                st.rerun()
    st.stop()

# GPS
loc = get_geolocation()
if loc and 'coords' in loc:
    lat_origem, lon_origem = loc['coords']['latitude'], loc['coords']['longitude']
else:
    st.warning("📍 Aguardando GPS...")
    st.stop()

# 2. TELA DE UPLOAD
if st.session_state['df_otimizado'] is None:
    st.subheader("🚚 Carregar Entregas")
    arquivo = st.file_uploader("Selecione o arquivo", type=['csv', 'xlsx'])
    if arquivo and st.button("CALCULAR ROTA"):
        df_raw = pd.read_csv(arquivo) if arquivo.name.endswith('.csv') else pd.read_excel(arquivo)
        
        # Agrupamento preservando AT ID, Sequence e SPX TN
        df = df_raw.groupby(['Latitude', 'Longitude'], as_index=False).agg({
            'AT ID': 'first',
            'Sequence': 'first',
            'SPX TN': 'first',
            'Destination Address': 'first',
            'Bairro': 'first',
            'City': 'first',
            'Stop': 'count'
        })
        
        # Otimização (Simplificada para garantir execução)
        coords = [[lat_origem, lon_origem]] + df[['Latitude', 'Longitude']].values.tolist()
        manager = pywrapcp.RoutingIndexManager(len(coords), 1, 0)
        routing = pywrapcp.RoutingModel(manager)
        def dist_call(f, t):
            p1 = coords[manager.IndexToNode(f)]; p2 = coords[manager.IndexToNode(t)]
            return int(sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2) * 111320)
        transit_idx = routing.RegisterTransitCallback(dist_call)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)
        sol = routing.SolveWithParameters(pywrapcp.DefaultRoutingSearchParameters())
        
        if sol:
            idx, ordem = routing.Start(0), []
            while not routing.IsEnd(idx):
                ordem.append(manager.IndexToNode(idx))
                idx = sol.Value(routing.NextVar(idx))
            st.session_state['df_otimizado'] = df.iloc[[i-1 for i in ordem if i > 0]].copy()
            st.rerun()

# 3. TELA DE OPERAÇÃO (ONDE AS MUDANÇAS ACONTECEM)
if st.session_state['df_otimizado'] is not None:
    df_res = st.session_state['df_otimizado']
    st_autorefresh(interval=30000, key="refresh")

    # Aba de Status (Apenas Pendente como solicitado)
    aba_pendente = st.tabs(["⏳ Pendente"])[0]

    with aba_pendente:
        # BOTÃO MOSTRAR MAPA / VOLTAR PARA LISTA
        if not st.session_state['ver_mapa']:
            if st.button("🗺️ MOSTRAR NO MAPA", use_container_width=True, type="primary"):
                st.session_state['ver_mapa'] = True
                st.rerun()
            
            # --- TELA DE LISTA (CARD ESTILO IMAGEM) ---
            proxima_idx = next((i for i in range(len(df_res)) if i not in st.session_state['entregas_feitas']), None)
            
            if proxima_idx is not None:
                dados = df_res.iloc[proxima_idx]
                
                # Card de Informações (Baseado na sua imagem)
                st.markdown("""---""")
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**AT:** {dados['AT ID']}")
                    st.write(f"**PEDIDO:** {dados['Sequence']}")
                with col2:
                    st.write(f"**PARADA:** {proxima_idx + 1}")
                    st.write(f"**BR:** {dados['SPX TN']}")
                
                st.info(f"🏠 **ENDEREÇO DESTINATÁRIO:**\n{dados['Destination Address']}")
                
                c1, c2 = st.columns(2)
                if c1.button("✅ ENTREGAR", use_container_width=True):
                    st.session_state['entregas_feitas'].add(proxima_idx)
                    st.rerun()
                
                g_maps = f"https://www.google.com/maps/dir/?api=1&origin={lat_origem},{lon_origem}&destination={dados['Latitude']},{dados['Longitude']}&travelmode=driving"
                c2.link_button("🚀 NAVEGAR", g_maps, use_container_width=True)
            else:
                st.success("🎉 Rota Concluída!")
                if st.button("Nova Rota"):
                    st.session_state['df_otimizado'] = None
                    st.session_state['ver_mapa'] = False
                    st.session_state['entregas_feitas'] = set()
                    st.rerun()

        else:
            # --- TELA DE MAPA ÚNICA ---
            if st.button("📋 VOLTAR PARA LISTA", use_container_width=True):
                st.session_state['ver_mapa'] = False
                st.rerun()
            
            m = folium.Map(location=[lat_origem, lon_origem], zoom_start=16)
            # Rota Fina
            pts = [[lat_origem, lon_origem]] + df_res[['Latitude', 'Longitude']].values.tolist()
            folium.PolyLine(obter_rota_ruas(pts), color="#444444", weight=3).add_to(m)
            
            # Marcadores numerados
            for i, row in enumerate(df_res.itertuples()):
                cor = "#28a745" if i in st.session_state['entregas_feitas'] else "#212529"
                icone = folium.DivIcon(html=f'<div style="background-color:{cor}; color:white; border-radius:4px; width:20px; height:20px; display:flex; align-items:center; justify-content:center; font-size:10px; font-weight:bold; border:1px solid white;">{i+1}</div>')
                folium.Marker([row.Latitude, row.Longitude], icon=icone).add_to(m)
            
            st_folium(m, width="100%", height=500, key="mapa_full")
