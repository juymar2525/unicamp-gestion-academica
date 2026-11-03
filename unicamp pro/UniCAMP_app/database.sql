CREATE DATABASE IF NOT EXISTS unicamp_horarios CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE unicamp_horarios;

CREATE TABLE IF NOT EXISTS docentes (
    id_docente INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(120) NOT NULL,
    especialidad VARCHAR(120) DEFAULT ''
);

CREATE TABLE IF NOT EXISTS materias (
    id_materia INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(120) NOT NULL,
    codigo VARCHAR(30) DEFAULT ''
);

CREATE TABLE IF NOT EXISTS aulas (
    id_aula INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(80) NOT NULL,
    capacidad INT NOT NULL DEFAULT 30
);

CREATE TABLE IF NOT EXISTS horarios (
    id_horario INT AUTO_INCREMENT PRIMARY KEY,
    id_docente INT NOT NULL,
    id_materia INT NOT NULL,
    id_aula INT NOT NULL,
    dia ENUM('Lunes','Martes','Miércoles','Jueves','Viernes','Sábado') NOT NULL,
    hora_inicio TIME NOT NULL,
    hora_fin TIME NOT NULL,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_h_docente FOREIGN KEY (id_docente) REFERENCES docentes(id_docente),
    CONSTRAINT fk_h_materia FOREIGN KEY (id_materia) REFERENCES materias(id_materia),
    CONSTRAINT fk_h_aula FOREIGN KEY (id_aula) REFERENCES aulas(id_aula),
    CONSTRAINT chk_horas CHECK (hora_fin > hora_inicio)
);

INSERT INTO docentes(nombre, especialidad)
SELECT 'Juan Pérez', 'Matemática' WHERE NOT EXISTS (SELECT 1 FROM docentes WHERE nombre='Juan Pérez');
INSERT INTO docentes(nombre, especialidad)
SELECT 'María González', 'Idiomas' WHERE NOT EXISTS (SELECT 1 FROM docentes WHERE nombre='María González');
INSERT INTO docentes(nombre, especialidad)
SELECT 'Carlos López', 'Programación' WHERE NOT EXISTS (SELECT 1 FROM docentes WHERE nombre='Carlos López');
INSERT INTO docentes(nombre, especialidad)
SELECT 'Ana Torres', 'Física' WHERE NOT EXISTS (SELECT 1 FROM docentes WHERE nombre='Ana Torres');
INSERT INTO docentes(nombre, especialidad)
SELECT 'Luis Martínez', 'Química' WHERE NOT EXISTS (SELECT 1 FROM docentes WHERE nombre='Luis Martínez');
INSERT INTO docentes(nombre, especialidad)
SELECT 'Sofía Ramírez', 'Historia' WHERE NOT EXISTS (SELECT 1 FROM docentes WHERE nombre='Sofía Ramírez');

INSERT INTO materias(nombre, codigo)
SELECT 'Matemática', 'MAT-01' WHERE NOT EXISTS (SELECT 1 FROM materias WHERE codigo='MAT-01');
INSERT INTO materias(nombre, codigo)
SELECT 'Inglés', 'ING-01' WHERE NOT EXISTS (SELECT 1 FROM materias WHERE codigo='ING-01');
INSERT INTO materias(nombre, codigo)
SELECT 'Programación', 'PRO-01' WHERE NOT EXISTS (SELECT 1 FROM materias WHERE codigo='PRO-01');
INSERT INTO materias(nombre, codigo)
SELECT 'Física', 'FIS-01' WHERE NOT EXISTS (SELECT 1 FROM materias WHERE codigo='FIS-01');
INSERT INTO materias(nombre, codigo)
SELECT 'Química', 'QUI-01' WHERE NOT EXISTS (SELECT 1 FROM materias WHERE codigo='QUI-01');
INSERT INTO materias(nombre, codigo)
SELECT 'Historia', 'HIS-01' WHERE NOT EXISTS (SELECT 1 FROM materias WHERE codigo='HIS-01');

INSERT INTO aulas(nombre, capacidad)
SELECT 'A-101',25 WHERE NOT EXISTS (SELECT 1 FROM aulas WHERE nombre='A-101');
INSERT INTO aulas(nombre, capacidad)
SELECT 'A-202',30 WHERE NOT EXISTS (SELECT 1 FROM aulas WHERE nombre='A-202');
INSERT INTO aulas(nombre, capacidad)
SELECT 'LAB-1',25 WHERE NOT EXISTS (SELECT 1 FROM aulas WHERE nombre='LAB-1');
INSERT INTO aulas(nombre, capacidad)
SELECT 'B-103',35 WHERE NOT EXISTS (SELECT 1 FROM aulas WHERE nombre='B-103');
INSERT INTO aulas(nombre, capacidad)
SELECT 'B-104',30 WHERE NOT EXISTS (SELECT 1 FROM aulas WHERE nombre='B-104');
INSERT INTO aulas(nombre, capacidad)
SELECT 'A-201',28 WHERE NOT EXISTS (SELECT 1 FROM aulas WHERE nombre='A-201');

INSERT INTO horarios(id_docente,id_materia,id_aula,dia,hora_inicio,hora_fin)
SELECT d.id_docente,m.id_materia,a.id_aula,'Lunes','07:00:00','09:00:00'
FROM docentes d,materias m,aulas a
WHERE d.nombre='Juan Pérez' AND m.codigo='MAT-01' AND a.nombre='A-101'
AND NOT EXISTS (SELECT 1 FROM horarios WHERE dia='Lunes' AND hora_inicio='07:00:00' AND id_docente=d.id_docente);

INSERT INTO horarios(id_docente,id_materia,id_aula,dia,hora_inicio,hora_fin)
SELECT d.id_docente,m.id_materia,a.id_aula,'Martes','09:00:00','11:00:00'
FROM docentes d,materias m,aulas a
WHERE d.nombre='María González' AND m.codigo='ING-01' AND a.nombre='A-202'
AND NOT EXISTS (SELECT 1 FROM horarios WHERE dia='Martes' AND hora_inicio='09:00:00' AND id_docente=d.id_docente);

INSERT INTO horarios(id_docente,id_materia,id_aula,dia,hora_inicio,hora_fin)
SELECT d.id_docente,m.id_materia,a.id_aula,'Miércoles','11:00:00','13:00:00'
FROM docentes d,materias m,aulas a
WHERE d.nombre='Carlos López' AND m.codigo='PRO-01' AND a.nombre='LAB-1'
AND NOT EXISTS (SELECT 1 FROM horarios WHERE dia='Miércoles' AND hora_inicio='11:00:00' AND id_docente=d.id_docente);

INSERT INTO horarios(id_docente,id_materia,id_aula,dia,hora_inicio,hora_fin)
SELECT d.id_docente,m.id_materia,a.id_aula,'Jueves','07:00:00','09:00:00'
FROM docentes d,materias m,aulas a
WHERE d.nombre='Ana Torres' AND m.codigo='FIS-01' AND a.nombre='B-103'
AND NOT EXISTS (SELECT 1 FROM horarios WHERE dia='Jueves' AND hora_inicio='07:00:00' AND id_docente=d.id_docente);

INSERT INTO horarios(id_docente,id_materia,id_aula,dia,hora_inicio,hora_fin)
SELECT d.id_docente,m.id_materia,a.id_aula,'Viernes','10:00:00','12:00:00'
FROM docentes d,materias m,aulas a
WHERE d.nombre='Luis Martínez' AND m.codigo='QUI-01' AND a.nombre='B-104'
AND NOT EXISTS (SELECT 1 FROM horarios WHERE dia='Viernes' AND hora_inicio='10:00:00' AND id_docente=d.id_docente);

INSERT INTO horarios(id_docente,id_materia,id_aula,dia,hora_inicio,hora_fin)
SELECT d.id_docente,m.id_materia,a.id_aula,'Sábado','08:00:00','10:00:00'
FROM docentes d,materias m,aulas a
WHERE d.nombre='Sofía Ramírez' AND m.codigo='HIS-01' AND a.nombre='A-201'
AND NOT EXISTS (SELECT 1 FROM horarios WHERE dia='Sábado' AND hora_inicio='08:00:00' AND id_docente=d.id_docente);
