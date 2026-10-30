-- Выполните в SQL Editor Supabase.
-- Каталог: публичное чтение, запись только с бота (service role).
-- Если таблица products уже есть, блок CREATE пропустите.

create table if not exists products (
    id bigint generated always as identity primary key,
    name text not null,
    price integer not null check (price >= 0),
    category text,
    flavor text,
    image text,
    stock integer
);

alter table products add column if not exists stock integer;

create table if not exists orders (
    id bigint generated always as identity primary key,
    user_id bigint not null,
    username text,
    full_name text,
    items jsonb not null,
    total integer not null check (total >= 0),
    status text not null default 'new',
    created_at timestamptz not null default now()
);

alter table products enable row level security;
alter table orders enable row level security;

drop policy if exists public_read_products on products;
create policy public_read_products on products
    for select
    to anon, authenticated
    using (true);

-- У anon нет политик на orders: вставить заказ может только service role бота.
