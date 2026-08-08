CREATE TABLE users (
  id INT PRIMARY KEY
);

CREATE TABLE items (
  id INT PRIMARY KEY,
  user_id INT NOT NULL,
  created_at DATETIME NOT NULL
);
