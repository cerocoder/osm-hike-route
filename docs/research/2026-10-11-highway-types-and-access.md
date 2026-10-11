# Типы дорог OSM (`highway=*`): кто по ним может двигаться и что их меняет

Дата: 2026-10-11. Язык документа — русский (по запросу). Источники: OSM wiki (`Key:highway`,
`Tag:highway=unclassified|tertiary|service`) и код навыков на коммите 9d4c7a0
(`presets/*.json`, `scripts/route_graph.py`).

Зачем: разбор отзыва `feedback/01_osm-test` показал, что пресет `bike-leisure` не пропускает
`unclassified`, `tertiary` и `service`, и в сельской местности граф дорог рассыпается. Здесь собрано,
что означает каждый тип дороги, кому по нему можно ехать/идти «в жизни» и что делают наши пресеты.

## Как читать

- **Роли:** 🚶 пешеход (`walk`), 🚲L велосипедист `bike/leisure`, 🚲S велосипедист `bike/sport`.
- **«В жизни»** — типичный доступ по умолчанию по правилам OSM (`access`-умолчания зависят от
  страны; ниже ориентир — общая практика и Россия). Конкретный участок решают теги-модификаторы.
- ✅ можно; ⚠️ можно с оговорками (опасно, зависит от тегов или страны); ❌ нельзя / не предназначено.
- **«Пресет»** — пропускает ли тип наш маршрутизатор сейчас (`routable_highway` в пресете).

## Таблица 1. Дороги для транспорта

| Тип | Суть (по wiki) | 🚶 | 🚲L | 🚲S | Пресет (🚶 / 🚲L / 🚲S) |
|---|---|---|---|---|---|
| `motorway` | Магистраль с ограниченным доступом, раздельные полосы, обычно обочина-«полоса аварийной остановки». | ❌ | ❌ | ❌ | нет / нет / нет |
| `trunk` | Важнейшие дороги страны, не магистрали; могут быть без разделителя. | ⚠️ | ⚠️ | ⚠️ | нет / только с `cycleway` / только с `cycleway` |
| `primary` | Следующий уровень, часто соединяет крупные города. | ⚠️ | ⚠️ | ⚠️ | нет / только с `cycleway` / только с `cycleway` |
| `secondary` | Следующий уровень, соединяет города. | ⚠️ | ⚠️ | ⚠️ | нет / нет / **да** |
| `tertiary` | Соединяет небольшие города и сёла; умеренный поток. | ✅ | ✅ | ✅ | **да** / нет / нет |
| `unclassified` | Малозначимая сквозная дорога между сёлами и хуторами; нежилая. Название — британский артефакт, **не** «тип неизвестен». Покрытие часто грунт. | ✅ | ✅ | ✅ | **да** / нет / нет |
| `residential` | Подъезды к жилью, улицы посёлков; не для связи населённых пунктов. | ✅ | ✅ | ✅ | да / да / да |
| `living_street` | Жилая зона, пешеходы в приоритете, очень низкая скорость. | ✅ | ✅ | ✅ | да / да / да |
| `service` | Подъезд к зданию, парковке, АЗС, промзоне, пляжу, кемпингу. Обычно не часть уличной сети, может быть частным. | ⚠️ | ⚠️ | ⚠️ | **да** / нет / нет |
| `track` | Хозяйственная/лесная дорога (сельхоз, лесовозы). Описывает назначение, а не качество (качество — `tracktype`). | ✅ | ✅ | ✅ | да / да / да |
| `road` | Тип неизвестен, временный тег до обследования. | ⚠️ | ⚠️ | ⚠️ | нет / нет / нет |
| `*_link` | Съезды и развязки к `motorway`, `trunk`, `primary`, `secondary`, `tertiary`; ограничения как у основной дороги. | см. родитель | см. родитель | см. родитель | см. «Замечание про регулярное выражение» |
| `busway`, `bus_guideway` | Выделенная полоса/трасса для автобусов. | ❌ | ❌ | ❌ | нет / нет / нет |
| `escape` | Съезд-улавливатель для грузовиков с отказавшими тормозами. | ❌ | ❌ | ❌ | нет / нет / нет |
| `raceway` | Трасса для автогонок. | ❌ | ❌ | ❌ | нет / нет / нет |

## Таблица 2. Пути и пешеходные типы

| Тип | Суть (по wiki) | 🚶 | 🚲L | 🚲S | Пресет (🚶 / 🚲L / 🚲S) |
|---|---|---|---|---|---|
| `path` | Неспецифичная тропа; wiki советует уточнять (`footway`, `cycleway`, `bridleway`, `track`). Допуск задают `foot`, `bicycle`, `horse`. | ✅ | ⚠️ | ⚠️ | да / да / да |
| `footway` | Пешеходная дорожка; для велосипедов — только если `bicycle=yes`. Включает тротуары и переходы (`footway=sidewalk\|crossing`). | ✅ | ⚠️ | ⚠️ | да / да / да |
| `pedestrian` | Пешеходная улица/площадь; транспорт ограничен или по времени. | ✅ | ⚠️ | ⚠️ | да / нет / нет |
| `cycleway` | Велодорожка; пешеходам — если `foot=yes` (умолчание зависит от страны). | ⚠️ | ✅ | ✅ | нет / да / да |
| `bridleway` | Дорожка для всадников; пешком обычно можно, на велосипеде — по местным правилам; моторный транспорт запрещён. | ✅ | ⚠️ | ⚠️ | нет / нет / нет |
| `steps` | Лестница (`step_count`). Велосипед только вести рядом. | ✅ | ❌ | ❌ | да / исключено / исключено |
| `corridor` | Коридор внутри здания. | ⚠️ | ❌ | ❌ | нет / нет / нет |
| `via_ferrata` | Скальный маршрут с тросами; нужны страховочная система и снаряжение. | ❌ | ❌ | ❌ | нет / нет / нет |
| `proposed`, `construction` | Планируется / строится. | ❌ | ❌ | ❌ | нет / нет / нет |

Строки `service`, `trunk`, `primary`, `secondary`, `footway`, `path`, `cycleway`, `pedestrian`
со значком ⚠️ описаны в «Оговорках» ниже.

## Модификаторы — что менять в оценке участка

Общие для всех типов:

| Тег | Что значит | Как влияет |
|---|---|---|
| `access=private\|no\|military` | Доступ закрыт | Наш код выкидывает как запретную зону (если нет `foot=yes\|designated` для пешехода или `bicycle=yes\|designated` для вело) |
| `access=destination\|customers\|permissive` | Только по делу / клиентам / терпимо | Не проверяется, нужен разбор вручную |
| `foot=*`, `bicycle=*`, `horse=*` | Допуск по виду движения: `yes`, `designated`, `permissive`, `no`, `dismount`, `discouraged` | `foot=no` выкидывает для пешехода; `bicycle=no\|dismount` выкидывает для вело (в обоих вело-пресетах) |
| `motor_vehicle=*`, `motorcar=*` | Допуск моторного транспорта | Не проверяется |
| `oneway=yes`, `oneway:bicycle=no` | Односторонняя; для вело может быть двусторонней | Учитывается только для вело (пешеход идёт в обе стороны); `cycleway=opposite*` тоже снимает запрет |
| `surface=*` | Покрытие: `asphalt`, `paved`, `compacted`, `gravel`, `dirt`, `sand`, `mud`, … | Только записывается в `segments` маршрута, в стоимости не участвует |
| `smoothness=*` | Ровность: от `excellent` до `impassable` | Только записывается |
| `tracktype=grade1..grade5` | Качество `track`: grade1 — асфальт/плотное, grade5 — мягкий грунт | Только записывается |
| `width`, `lanes`, `maxspeed` | Ширина, полосы, ограничение скорости | Не используются |
| `bridge=*`, `tunnel=*` | Мост / тоннель (`tunnel=flooded` — затоплен) | `flooded` исключается; тоннель `motorway`/`trunk` проходим только с `foot=yes\|designated` или тротуаром и длиной ≤ 15 м |
| `ford=yes` | Брод | Не учитывается (в половодье опасен) |
| `incline=*` | Уклон | Уклон считаем по высотам, тег игнорируется |
| `lit=*`, `winter_service=*`, `snowplowing=*` | Освещение, зимнее обслуживание, чистка снега | Записывается; нужен для зимней проходимости |
| `barrier=*` на узле | Шлагбаум, калитка, `cycle_barrier`, `turnstile` | Для вело блокируют `cycle_barrier` и `turnstile`; закрытый (`locked=yes`, `access=private\|no`) блокирует всех |

Специфичные для типа:

| Тип | Модификаторы |
|---|---|
| `motorway`, `trunk`, `primary`, `secondary`, `tertiary` | `motorroad=yes` (только для моторных), `cycleway`, `cycleway:left\|right\|both` (`lane`, `track`, `shared_lane`, `opposite*`, `no`, `separate`), `sidewalk`, `sidewalk:left\|right\|both`, `shoulder`, `lanes`, `maxspeed`, `ref`, `oneway`, `junction=roundabout` |
| `unclassified`, `residential`, `living_street` | `surface` (ключевое для сельских: асфальт или грунт), `maxspeed`, `sidewalk`, `cycleway*`, `oneway`, `zone:maxspeed`, `traffic_calming` |
| `service` | `service=driveway\|parking_aisle\|alley\|emergency_access\|drive-through` (подтип решает всё), `access`, `motor_vehicle=destination`, `oneway`, `surface`, `lit` |
| `track` | `tracktype`, `surface`, `smoothness`, `4wd_only`, `mtb:scale`, `trail_visibility`, `seasonal`, `access` (часто `agricultural\|forestry`) |
| `path` | `foot`, `bicycle`, `horse`, `sac_scale` (`hiking` … `difficult_alpine_hiking`), `mtb:scale` (0–6), `mtb:scale:uphill`, `trail_visibility`, `surface`, `width`, `incline`, `informal=yes` |
| `footway` | `footway=sidewalk\|crossing\|link\|traffic_island`, `bicycle=yes\|no`, `crossing=*`, `tactile_paving`, `surface`, `incline` |
| `pedestrian` | `area=yes` (площадь), `bicycle`, `vehicle=delivery\|destination`, временные ограничения (`:conditional`) |
| `cycleway` | `foot=yes\|no`, `segregated=yes\|no` (раздельное движение с пешеходами), `surface`, `lit`, `oneway` |
| `bridleway` | `horse=designated`, `foot`, `bicycle`, `surface` |
| `steps` | `step_count`, `handrail`, `ramp=yes` (есть пандус; ramp:bicycle — канавка для колеса), `incline` |
| `*_link` | Как у родителя: `oneway=yes` почти всегда, `cycleway`, `foot`, `bicycle` |

## Оговорки к ⚠️

- **`trunk`, `primary`, `secondary`.** Законодательно ехать/идти по ним обычно можно (кроме отдельных
  знаков и `motorroad=yes`), но на «чистой» дороге без обочины или велодорожки это опасно. Наши
  вело-пресеты берут `trunk` и `primary` только с `cycleway*`, а `secondary` — только в `bike-sport`. Для
  пешехода `secondary`, `primary` и `trunk` не пропускаются совсем.
- **`service`.** Подтипы `parking_aisle`, `driveway`, `emergency_access`, а также `access=private\|no`
  — это не маршрут. `alley` и безымянный подъезд к пляжу/кемпингу часто годятся. Сейчас пешеходный пресет
  берёт `service` целиком, вело-пресеты — вообще нет.
- **`footway`, `pedestrian`, `path` для велосипеда.** Езда по `footway` и `pedestrian` без `bicycle=yes`
  в ряде стран запрещена; правила по странам не проверялись (для России ПДД не сверялись). Пресеты `bike-*` берут
  `footway` без проверки, `bicycle=no` и `dismount` отсекаются, а отсутствие тега — нет. `path` без
  тегов обычно проходим на велосипеде, но смотрите `mtb:scale`, `sac_scale` и `surface`.
- **`cycleway` для пешехода.** Умолчание по `foot` зависит от страны; пешеходный пресет `cycleway` не берёт,
  поэтому участки «велодорожка вдоль реки» пешком не используются, даже когда это единственный проход.
- **`pedestrian` для велосипеда.** Обычно запрещено без явного `bicycle=yes`; пресеты `bike-*` не берут тип.

## Замечание про регулярное выражение (по чтению кода, в запуске не проверено)

Запрос к Overpass (`route_graph.fetch_area_data`) собирает `walkable_pattern` как `"|".join(...)` и ищет
`way["highway"~"..."]` без якорей `^…$`. Поэтому значение, содержащее подстроку, попадает в выборку:
`trunk_link` и `primary_link` попадают в запрос из-за `trunk`/`primary`, `secondary_link` (в `bike-sport`) —
из-за `secondary`, `tertiary_link` (в `walk`) — из-за `tertiary`. Фильтр `_lacks_required_cycle_infra`
сравнивает `highway` с точным значением, поэтому `trunk_link` и `primary_link` не отбрасываются как
«дорога без велоинфраструктуры» и проходят в граф. Нужно проверить на реальных данных и,
если подтвердится, привязать шаблон якорями и решить отдельно, нужны ли нам `*_link`.

## Что из этого следует для пресетов

Решения приняты 2026-10-11 (TODO 9, см. спеку §3.6.1): `service` и `road` — запасные (fallback) для вело; `footway`/`pedestrian` для вело без `bicycle=yes|designated` — запасные; `steps` разрешены с наценкой; `corridor`, `bridleway`, `tertiary`, `unclassified` разрешены; регулярное выражение привязано якорями, `*_link` больше не запрашиваются. Ниже — исходный список вопросов.

1. `bike-leisure` и `bike-sport`: добавить `unclassified` и `tertiary` (сельская сеть связи между сёлами; на
   `unclassified` часто нет асфальта, это нормально для прогулки).
2. `service`: не добавлять целиком. Брать только если нет `service=parking_aisle|driveway|emergency_access`
   и нет `access=private|no`, либо использовать как запасной вариант для восстановления связности.
3. `footway`/`pedestrian` для вело: решить, требовать ли явный `bicycle=yes|designated`.
4. Проверить замечание про регулярное выражение и `*_link`.
5. `cycleway` и `bridleway` для пешехода, `pedestrian` и `bridleway` для вело: решить отдельно.
