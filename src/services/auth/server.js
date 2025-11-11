const express = require('express');
const bcrypt = require('bcrypt');
const jwt = require('jsonwebtoken');
const Joi = require('joi');
const helmet = require('helmet');
const cors = require('cors');
const { Pool } = require('pg');
require('dotenv').config();

// Configuración de la APP
const app = express();
const PORT = process.env.PORT || 3001;
const JWT_SECRET = process.env.JWT_SECRET || 'default-dev-secret';

// 🛡️ FIX R#13: Conexión persistente a PostgreSQL
// Usamos las variables EXACTAS de tu docker-compose.yml para garantizar conexión.
const pool = new Pool({
  host: process.env.POSTGRES_HOST || 'haproxy', // Fallback seguro a haproxy si falta la env
  port: process.env.POSTGRES_PORT || 5432,
  user: process.env.POSTGRES_USER || 'postgres',
  password: process.env.POSTGRES_PASSWORD || 'postgres',
  database: process.env.POSTGRES_DB || 'tutor_ia_db',
  // Configuración de robustez para producción
  connectionTimeoutMillis: 5000, // Tiempo máx para intentar conectar (5s)
  query_timeout: 10000,          // Tiempo máx para ejecutar una query (10s)
  max: 20                        // Máximo de conexiones simultáneas en el pool
});

// Verificar conexión al iniciar (sin matar el proceso si falla inicialmente)
pool.query('SELECT NOW()', (err, res) => {
  if (err) {
    console.error('❌ [Auth-Service] Error fatal: No se pudo conectar a PostgreSQL vía HAProxy.', err.message);
    console.error('   -> Verifica que el servicio "haproxy" esté saludable y las credenciales en .env sean correctas.');
  } else {
    console.log('✅ [Auth-Service] Conectado exitosamente a PostgreSQL DB:', process.env.POSTGRES_DB);
  }
});

// Middleware de seguridad y parseo
app.use(helmet());
app.use(cors());
app.use(express.json());

// --- Esquemas de validación Joi ---
const registerSchema = Joi.object({
  name: Joi.string().min(2).max(50).required(),
  email: Joi.string().email().required(),
  password: Joi.string().min(6).required()
});

const loginSchema = Joi.object({
  email: Joi.string().email().required(),
  password: Joi.string().required()
});

// --- RUTAS ---

// Registro de usuario (PERSISTENTE)
app.post('/auth/register', async (req, res) => {
  try {
    // 1. Validar input
    const { error, value } = registerSchema.validate(req.body);
    if (error) return res.status(400).json({ error: 'Datos inválidos', details: error.details[0].message });

    const { name, email, password } = value;

    // 2. Hash de contraseña (seguridad)
    const saltRounds = 10;
    const hashedPassword = await bcrypt.hash(password, saltRounds);

    // 3. INSERT en la base de datos real
    const query = `
      INSERT INTO users (name, email, password_hash)
      VALUES ($1, $2, $3)
      RETURNING id, name, email, created_at;
    `;

    const result = await pool.query(query, [name, email, hashedPassword]);
    const newUser = result.rows[0];

    console.log(`👤 [Auth] Nuevo usuario registrado: ${email}`);
    res.status(201).json({
      message: 'Usuario registrado exitosamente',
      user: newUser
    });

  } catch (error) {
    // Código '23505' = unique_violation (email ya existe)
    if (error.code === '23505') {
      return res.status(409).json({ error: 'El email ya está registrado' });
    }
    console.error('❌ [Auth] Error en registro:', error);
    res.status(500).json({ error: 'Error interno del servidor' });
  }
});

// Login de usuario (PERSISTENTE)
app.post('/auth/login', async (req, res) => {
  try {
    // 1. Validar input
    const { error, value } = loginSchema.validate(req.body);
    if (error) return res.status(400).json({ error: 'Datos inválidos', details: error.details[0].message });

    const { email, password } = value;

    // 2. Buscar usuario en la DB
    const result = await pool.query('SELECT id, name, email, password_hash FROM users WHERE email = $1', [email]);
    const user = result.rows[0];

    if (!user) return res.status(401).json({ error: 'Email o contraseña incorrectos' });

    // 3. Verificar contraseña
    const passwordMatch = await bcrypt.compare(password, user.password_hash);
    if (!passwordMatch) return res.status(401).json({ error: 'Email o contraseña incorrectos' });

    // 4. Generar Token JWT
    const token = jwt.sign(
      { userId: user.id, email: user.email },
      JWT_SECRET,
      { expiresIn: '24h' }
    );

    res.json({
      message: 'Login exitoso',
      token,
      user: { id: user.id, name: user.name, email: user.email }
    });

  } catch (error) {
    console.error('❌ [Auth] Error en login:', error);
    res.status(500).json({ error: 'Error interno del servidor' });
  }
});

// Verificar token (Stateless - sigue igual)
app.get('/auth/verify', (req, res) => {
  try {
    const token = req.headers.authorization?.replace('Bearer ', '');
    if (!token) return res.status(401).json({ error: 'Token no proporcionado' });

    const decoded = jwt.verify(token, JWT_SECRET);
    res.json({ valid: true, user: { userId: decoded.userId, email: decoded.email } });
  } catch (error) {
    res.status(401).json({ valid: false, error: 'Token inválido' });
  }
});

// Health Check (Real - verifica conexión a DB)
app.get('/health', async (req, res) => {
  try {
    await pool.query('SELECT 1'); // Ping a la DB
    res.json({
      status: 'ok',
      service: 'auth-service',
      db_connection: 'healthy',
      timestamp: new Date().toISOString()
    });
  } catch (error) {
    res.status(503).json({
      status: 'error',
      service: 'auth-service',
      db_connection: 'unhealthy',
      error: error.message
    });
  }
});

// Iniciar servidor
app.listen(PORT, () => {
  console.log(`🔐 Auth Service corriendo en puerto ${PORT}`);
});