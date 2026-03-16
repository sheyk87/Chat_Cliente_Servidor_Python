# 💬 Chat App Empresarial (Cliente-Servidor TCP)

Un sistema de mensajería corporativa robusto, seguro y eficiente desarrollado completamente en Python utilizando Sockets TCP puros y una arquitectura Multihilo. Diseñado para soportar mensajería en tiempo real, transferencia segura de archivos por streaming de bloques (chunks) y una gestión administrativa avanzada.

---

## 🚀 Características Principales

### 🔒 Seguridad e Integridad
* **Protección de Credenciales:** Las contraseñas nunca viajan ni se almacenan en texto plano. Se utiliza cifrado **SHA-256 con "Salt"** para evitar ataques de diccionarios (Rainbow tables).
* **Control de Integridad de Archivos:** Las transferencias de archivos utilizan hashing SHA-256. El servidor calcula y compara la "huella digital" del archivo original contra el archivo recibido; si se detecta la pérdida de un solo byte (corrupción), la transferencia se rechaza automáticamente.
* **Tolerancia a Fragmentación TCP:** Implementación de un búfer inteligente con decodificación "Raw JSON" que acumula y procesa fragmentos de red, evitando bloqueos o pérdida de mensajes por paquetes TCP cortados.

### 👥 Gestión de Usuarios y Permisos (ABM)
* **Perfiles de Usuario:** Distinción entre Usuarios estándar y Administradores.
* **Administración Centralizada:** Los administradores pueden crear, editar, eliminar cuentas, forzar cambios de contraseña y promover otros usuarios a roles de administración en tiempo real.
* **Modo Impersonación (Modo Dios):** Función exclusiva para Administradores que permite "tomar control" de la cuenta de cualquier usuario para auditoría visual o soporte, pudiendo retornar a su cuenta original de forma segura.

### 🏢 Gestión de Grupos (Salas de Chat)
* **Salas Dinámicas:** Creación de grupos privados y públicos.
* **Roles de Grupo (Gestores):** Los creadores y usuarios designados como "Gestores" tienen permisos elevados dentro del grupo.
* **Control de Participación:** Los gestores pueden expulsar/añadir miembros de forma masiva y cambiar los roles de otros usuarios.
* **Modo "Solo Gestores":** Capacidad de bloquear un grupo para que los usuarios estándar solo puedan leer, limitando la escritura a los Gestores (ideal para canales de anuncios).
* **Gestión de Historial:** Los gestores pueden vaciar el historial del chat para todos los miembros del grupo.

### ✉️ Mensajería y Herramientas de Chat
* **Mensajes Directos y Grupales:** Comunicación instantánea con actualización de estado (Online/Offline) en tiempo real.
* **Respuestas Contextuales:** Posibilidad de responder a mensajes específicos (Reply-to) con trazabilidad visual en el chat.
* **Gestión de Historial Local:** Los usuarios pueden vaciar historiales de chats directos de su propia interfaz.

### 📂 Transferencia de Archivos (Streaming por Chunks)
* **Subidas y Descargas en Segundo Plano:** En lugar de enviar archivos pesados en un solo bloque (lo que congela la interfaz y satura la memoria RAM), el sistema corta el archivo en pequeños fragmentos (Chunks de 512KB para subida, 256KB para descarga).
* **Gestor de Archivos de Chat:** Un panel dedicado por chat para ver, descargar y eliminar archivos compartidos históricamente en esa conversación.
* **Prevención de Sobreescritura:** Descargas seguras que auto-renombran archivos (ej. `archivo(1).pdf`) si el fichero ya existe en el directorio local.

### 🕵️‍♂️ Sistema de Auditoría
* **Trazabilidad Total:** Registro automático en Base de Datos de cada evento crucial: Logins, Logouts, creaciones de grupos, cambios de roles, expulsiones, envíos y descargas de archivos.
* **Panel de Auditoría Filtrable:** Interfaz para el Administrador con búsqueda en tiempo real por IP, fecha, usuario o acción.
* **Exportación CSV:** Capacidad de exportar los logs de auditoría filtrados a una hoja de cálculo para análisis externo.

---

## 🧠 Arquitectura del Sistema

El proyecto sigue un modelo estricto **Cliente-Servidor**.
* **El Servidor (`server.py`):** Actúa como el núcleo central. Maneja la concurrencia delegando cada conexión entrante a un hilo (`Threading`) dedicado. Interactúa exclusivamente con la base de datos SQLite y actúa como un "Router" de mensajes, determinando a quién debe retransmitirse cada paquete.
* **El Cliente (`client.py`):** Mantiene una conexión persistente (Keep-Alive) con el servidor. Utiliza un hilo secundario de escucha en bucle continuo para no bloquear la interfaz gráfica (UI) construida en `Tkinter`.

### Diagrama de Arquitectura de Red

```mermaid
graph TD
    subgraph Clientes
        C1[Cliente 1 - UI]
        C2[Cliente 2 - UI]
        C3[Cliente N - UI]
    end

    subgraph Servidor Central
        S[Servidor de Sockets TCP]
        T1((Hilo C1))
        T2((Hilo C2))
        TN((Hilo CN))
        S --> T1
        S --> T2
        S --> TN
    end

    subgraph Almacenamiento
        DB[(chat_app.db SQLite)]
        FS[Sistema de Archivos Local]
    end

    C1 <==> |JSON sobre TCP| T1
    C2 <==> |JSON sobre TCP| T2
    C3 <==> |JSON sobre TCP| TN

    T1 --> DB
    T2 --> DB
    TN --> FS


### Diagrama de Flujo: Transferencia de Archivos Segura (Streaming)

La transmisión de archivos evita los cuellos de botella en la memoria y en la red mediante una negociación previa, envío por fragmentos (chunks) y verificación criptográfica final.

```mermaid
sequenceDiagram
    participant C as Cliente Remitente
    participant S as Servidor Central
    participant D as Destinatario(s)

    C->>C: Calcula Hash SHA-256 del archivo original
    C->>S: [INICIO_ARCHIVO] (Nombre, Destino, Hash SHA-256)
    S->>S: Reserva memoria y genera Transfer_ID único
    S-->>C: [PERMISO_ENVIO_CHUNKS] (Transfer_ID)
    
    loop Lectura en Hilo Secundario (Chunks de 512KB)
        C->>S: [CHUNK_ARCHIVO] (Base64, Transfer_ID)
        S->>S: Escribe datos binarios progresivamente en disco local
    end
    
    C->>S: [FIN_ARCHIVO] (Transfer_ID)
    S->>S: Calcula Hash SHA-256 del archivo recibido en disco
    
    alt Hashes No Coinciden
        S->>S: Elimina el archivo corrupto del disco
        S-->>C: [ERROR] (Corrupción detectada en la transferencia)
    else Hashes Coinciden
        S->>S: Registra metadatos en Base de Datos SQLite
        S-->>C: [CONFIRMACION_ARCHIVO]
        S-->>D: [NUEVO_MENSAJE] (Notificación de archivo adjunto en el chat)
    end
