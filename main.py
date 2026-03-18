from fastapi import FastAPI

from fastapi.middleware.cors import CORSMiddleware

from database import engine, Base

import models

from routes import clientes



                                                                       

Base.metadata.create_all(bind=engine)



app = FastAPI(title="ISP Management API")



                       

origins = [

    "*",

]



app.add_middleware(

    CORSMiddleware,

    allow_origins=origins,

    allow_credentials=False,

    allow_methods=["*"],

    allow_headers=["*"],

)



                               

app.include_router(clientes.router)



@app.get("/")

def read_root():

    return {"message": "Bienvenido a la API de Gestión de ISP Opsatel"}

