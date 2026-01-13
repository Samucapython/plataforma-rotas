import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from math import radians, cos, sin, asin, sqrt
import requests
from streamlit_autorefresh import st_autorefresh

# 1. FUNÇÕES TÉCNICAS
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi, dlambda = radians(lat2-lat1), radians(lon2-lon1)
    a = sin(dphi/2)**2 + cos(phi1)*cos(phi2)*sin(dlambda/2)**2
    return 2 * R * asin(sqrt(a))

def obter_rota_ruas(coords_list):
    try:
        locs = ";".join([f"{lon},{lat}" for lat, lon in coords_list])
        url = f"http://router.project-osrm.org/route/v1/driving/{locs}?overview=full&geometries=geojson"
        r = requests.get(url, timeout=10)
        return [[p[1], p[0]] for p in r.json()['routes'][0]['geometry']['coordinates']]
    except: return coords_list

st.set_page_config(page_title="Samuel Rota Pro", layout="wide")

if 'df_otimizado' not in st.session_state: st.session_state['df_otimizado'] = None
if 'entregas_feitas' not in st.session_state: st.session_state['entregas_feitas'] = set()
if 'ver_mapa' not in st.session_state: st.session_state['ver_mapa'] = False

# GPS
loc = get_geolocation()
if loc and 'coords' in loc:
    lat_vtr, lon_vtr = loc['coords']['latitude'], loc['coords']['longitude']
else:
    st.warning("📍 Aguardando GPS...")
    st.stop()

# 2. PROCESSAMENTO (AGRUPAMENTO + RESET DE ÍNDICE)
if st.session_state['df_otimizado'] is None:
    arquivo = st.file_uploader("Subir Planilha", type=['csv', 'xlsx'])
    if arquivo and st.button("OTIMIZAR ROTA"):
        df_raw = pd.read_csv(arquivo) if arquivo.name.endswith('.csv') else pd.read_excel(arquivo)
        
        # Agrupa por endereço completo para reduzir paradas inúteis
        df_grouped = df_raw.groupby(['Destination Address', 'Latitude', 'Longitude'], as_index=False).agg({
            'AT ID': 'first',
            'Sequence': 'first',
            'SPX TN': lambda x: " | ".join(x.astype(str)),
            'Stop': 'count'
        })
        
        # Otimização de Rota (Cálculo do melhor trajeto)
        coords = [[lat_vtr, lon_vtr]] + df_grouped[['Latitude', 'Longitude']].values.tolist()
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
            
            # CRIAÇÃO DA ROTA FINAL E RESET DE ÍNDICE (CORREÇÃO DO SALTO)
            df_final = df_grouped.iloc[[i-1 for i in ordem if i > 0]].copy()
            df_final = df_final.reset_index(drop=True) # <--- AQUI OS NÚMEROS VOLTAM A SER 0, 1, 2, 3...
            
            st.session_state['df_otimizado'] = df_final
            st.rerun()

# 3. INTERFACE
if st.session_state['df_otimizado'] is not None:
    st_autorefresh(interval=25000, key="nav_refresh")
    df_res = st.session_state['df_otimizado']
    proxima_idx = next((i for i in range(len(df_res)) if i not in st.session_state['entregas_feitas']), None)

    # Auto-Baixa (Finaliza automaticamente ao chegar perto)
    if proxima_idx is not None:
        r = df_res.iloc[proxima_idx]
        if haversine(lat_vtr, lon_vtr, r.Latitude, r.Longitude) < 30:
            st.session_state['entregas_feitas'].add(proxima_idx)
            st.rerun()

    if not st.session_state['ver_mapa']:
        # --- TELA DE LISTA ---
        st.button("🗺️ VER NO MAPA", on_click=lambda: st.session_state.update({"ver_mapa": True}), use_container_width=True)
        if proxima_idx is not None:
            dados = df_res.iloc[proxima_idx]
            st.subheader(f"📍 Parada {proxima_idx + 1}")
            st.info(f"🏠 {dados['Destination Address']}")
            st.write(f"📦 **BRs:** {dados['SPX TN']}")
            
            # Navegação direta para o Google Maps
            g_maps = f"https://www.google.com/maps/dir/?api=1&origin={lat_vtr},{lon_vtr}&destination={dados.Latitude},{dados.Longitude}&travelmode=driving"
            st.link_button("🚀 NAVEGAR", g_maps, use_container_width=True)
            
            if st.button("Finalizar Manualmente"):
                st.session_state['entregas_feitas'].add(proxima_idx)
                st.rerun()
        else:
            st.success("🎉 Todas as entregas foram concluídas!")
            if st.button("Reiniciar Rota"):
                st.session_state['df_otimizado'] = None
                st.session_state['entregas_feitas'] = set()
                st.rerun()
    else:
        # --- TELA DE MAPA ---
        st.button("📋 VOLTAR PARA LISTA", on_click=lambda: st.session_state.update({"ver_mapa": False}), use_container_width=True)
        m = folium.Map(location=[lat_vtr, lon_vtr], zoom_start=16)
        
        # Traçado da Rota seguindo as ruas
        pts = [[lat_vtr, lon_vtr]] + df_res[['Latitude', 'Longitude']].values.tolist()
        folium.PolyLine(obter_rota_ruas(pts), color="#444444", weight=3, opacity=0.7).add_to(m)
        
        # Marcador do Motorista
        folium.CircleMarker([lat_vtr, lon_vtr], radius=5, color="red", fill=True).add_to(m)

        # Marcadores das Paradas
        for i, row in enumerate(df_res.itertuples()):
            # Cor: Verde se entregue, Preto se pendente
            cor = "#28a745" if i in st.session_state['entregas_feitas'] else "#212529"
            
            # Conteúdo: Casinha para atribuição ou o número da parada (i+1)
            if str(row.Sequence) == '-':
                conteudo_icone = '<i class="fa fa-home" style="font-size:10px;"></i>'
            else:
                conteudo_icone = f"{i+1}"
            
            icone = folium.DivIcon(html=f"""
                <div style="background-color:{cor}; color:white; border-radius:4px; width:20px; height:20px; 
                display:flex; align-items:center; justify-content:center; font-weight:bold; font-size:10px; 
                border:1px solid white;">{conteudo_icone}</div>""")
            
            folium.Marker([row.Latitude, row.Longitude], icon=icone, 
                          popup=f"Parada {i+1}<br>{row._1}").add_to(m)

        st_folium(m, width="100%", height=600)
