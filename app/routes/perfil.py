from fastapi import APIRouter

from app.profile import salvar_perfil
from app.schemas import PerfilRequest

router = APIRouter(tags=["perfil"])

@router.post("/perfil")
def criar_ou_atualizar_perfil(perfil: PerfilRequest):
    return salvar_perfil(
        user_id=perfil.user_id,
        renda_mensal=perfil.renda_mensal,
        objetivo=perfil.objetivo,
        tolerancia_risco=perfil.tolerancia_risco,
        preferencias=perfil.preferencias,
    )