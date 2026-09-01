from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import JWTError, jwt
import models, schemas, auth_utils
from database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudo validar el acceso",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, auth_utils.SECRET_KEY, algorithms=[auth_utils.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(models.Usuario).filter(models.Usuario.username == username).first()
    if user is None:
        raise credentials_exception
    return user

def require_role(roles: list):
    def role_checker(current_user: models.Usuario = Depends(get_current_user)):
        if current_user.rol not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para realizar esta acción"
            )
        return current_user
    return role_checker

@router.post("/register", response_model=schemas.UsuarioResponse, dependencies=[Depends(require_role(["administrador"]))])
def registrar_usuario(usuario: schemas.UsuarioCreate, db: Session = Depends(get_db)):
    # Verificar si ya existe
    db_user = db.query(models.Usuario).filter(models.Usuario.username == usuario.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="El usuario ya existe")
    
    nuevo_usuario = models.Usuario(
        username=usuario.username,
        password_hash=auth_utils.get_password_hash(usuario.password),
        rol=usuario.rol
    )
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    return nuevo_usuario

@router.get("/usuarios", response_model=list[schemas.UsuarioResponse], dependencies=[Depends(require_role(["administrador", "secretario", "tecnico", "instalador"]))])
def listar_usuarios(db: Session = Depends(get_db)):
    return db.query(models.Usuario).all()

@router.get("/tecnicos", response_model=list[schemas.UsuarioResponse], dependencies=[Depends(require_role(["administrador", "secretario", "tecnico", "instalador"]))])
def listar_tecnicos(db: Session = Depends(get_db)):
    return db.query(models.Usuario).filter(models.Usuario.rol == "tecnico").all()

@router.patch("/usuarios/{usuario_id}", response_model=schemas.UsuarioResponse, dependencies=[Depends(require_role(["administrador"]))])
def actualizar_usuario(usuario_id: int, usuario_data: schemas.UsuarioCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    db_user.username = usuario_data.username
    if usuario_data.password:
        db_user.password_hash = auth_utils.get_password_hash(usuario_data.password)
    db_user.rol = usuario_data.rol
    
    db.commit()
    db.refresh(db_user)
    return db_user

@router.delete("/usuarios/{usuario_id}", dependencies=[Depends(require_role(["administrador"]))])
def eliminar_usuario(usuario_id: int, db: Session = Depends(get_db)):
    db_user = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Eliminar registros relacionados para evitar errores de Foreign Key (Constraint)
    db.query(models.Asistencia).filter(models.Asistencia.usuario_id == usuario_id).delete()
    
    db.delete(db_user)
    db.commit()
    return {"message": "Usuario eliminado correctamente"}

@router.post("/login", response_model=schemas.Token)
def login(usuario: schemas.UsuarioAuth, db: Session = Depends(get_db)):
    db_user = db.query(models.Usuario).filter(models.Usuario.username == usuario.username).first()
    if not db_user or not auth_utils.verify_password(usuario.password, db_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = auth_utils.create_access_token(
        data={"sub": db_user.username, "rol": db_user.rol}
    )
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "username": db_user.username,
        "rol": db_user.rol
    }
